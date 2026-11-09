"""Small, deterministic local coding fixtures; not an industry benchmark."""
TASKS = [
    {
        'id': 'ttl_lru_cache',
        'language': 'python',
        'files': {'cache.py': '''from collections import OrderedDict
import time

class TTLCache:
    def __init__(self, capacity, clock=time.monotonic):
        self.capacity = capacity
        self.clock = clock
        self.items = OrderedDict()

    def put(self, key, value, ttl):
        self.items[key] = (value, self.clock() + ttl)
        if len(self.items) > self.capacity:
            self.items.popitem()

    def get(self, key, default=None):
        item = self.items.get(key)
        if item is None:
            return default
        value, expires = item
        if self.clock() > expires:
            return default
        return value
''', 'README.txt': '''Fix TTLCache without changing its public API. Capacity must be a positive integer (bool is invalid), otherwise raise ValueError. Implement least-recently-used eviction: successful get and put refresh recency. Remove expired entries before eviction. An entry is expired when now >= expiry. A non-positive ttl removes the given key and does not insert it. get returns default for absent/expired keys, including when stored values are None or falsy. Use the injected clock. Do not add dependencies.'''
        },
        'tests': '''import unittest
from cache import TTLCache
class Tests(unittest.TestCase):
 def setUp(self): self.now=0; self.c=TTLCache(2,lambda:self.now)
 def test_lru_get(self):
  self.c.put('a',1,10); self.c.put('b',2,10); self.c.get('a'); self.c.put('c',3,10)
  self.assertEqual(self.c.get('a'),1); self.assertIsNone(self.c.get('b')); self.assertEqual(self.c.get('c'),3)
 def test_update_recency(self):
  self.c.put('a',1,10); self.c.put('b',2,10); self.c.put('a',4,10); self.c.put('c',3,10)
  self.assertEqual(self.c.get('a'),4); self.assertIsNone(self.c.get('b'))
 def test_expired_boundary(self):
  self.c.put('a',1,2); self.now=2; self.assertEqual(self.c.get('a','missing'),'missing')
 def test_expired_before_eviction(self):
  self.c.put('a',1,10); self.c.put('b',2,1); self.now=2; self.c.put('c',3,10)
  self.assertEqual(self.c.get('a'),1); self.assertEqual(self.c.get('c'),3)
 def test_nonpositive_ttl(self):
  self.c.put('a',1,10); self.c.put('a',2,0); self.assertEqual(self.c.get('a','x'),'x')
  self.c.put('b',1,-2); self.assertEqual(self.c.get('b','x'),'x')
 def test_falsy(self):
  for v in (None,False,0,''):
   self.c.put('x',v,10); self.assertIs(self.c.get('x','fallback'),v)
 def test_validation(self):
  for v in (0,-1,1.2,True,'2'):
   with self.assertRaises(ValueError): TTLCache(v)
 def test_new_expiry(self):
  self.c.put('a',1,1); self.now=.5; self.c.put('a',2,10); self.now=2; self.assertEqual(self.c.get('a'),2)
'''
    },
    {
        'id': 'money_multifile',
        'language': 'python',
        'files': {
            'money.py': '''def line_total(price, quantity, discount_percent=0):
    return round(float(price) * quantity * (1 - float(discount_percent) / 100), 2)
''',
            'checkout.py': '''from money import line_total

def checkout(items, discount_percent=0, shipping='0.00'):
    subtotal = sum(line_total(i['price'], i['quantity']) for i in items)
    return round(subtotal + float(shipping), 2)
''',
            'README.txt': '''Repair both modules. All money results must be Decimal quantized to two places with ROUND_HALF_UP. Convert inputs with Decimal(str(value)), never binary floating point arithmetic. line_total(price, quantity, discount_percent=0) applies discount before rounding; reject negative/nonfinite price, non-integer or negative quantity (including bool), and nonfinite or outside-0..100 discount, with ValueError. checkout(items, discount_percent=0, shipping='0.00') applies the same discount separately to each line, sums those rounded line totals, then adds shipping rounded HALF_UP to cents; shipping must be finite/nonnegative. Empty basket returns rounded shipping, but still validates discount. Reject invalid numeric inputs with ValueError. Preserve the public function signatures. No dependencies.'''
        },
        'tests': '''import unittest
from decimal import Decimal
from money import line_total
from checkout import checkout
class Tests(unittest.TestCase):
 def test_half_up(self): self.assertEqual(line_total('1.005',1),Decimal('1.01'))
 def test_type(self): self.assertIsInstance(line_total('2',2),Decimal)
 def test_discount(self): self.assertEqual(line_total('19.99',3,'15'),Decimal('50.97'))
 def test_checkout_discount(self): self.assertEqual(checkout([{'price':'10','quantity':2}],10,'1.255'),Decimal('19.26'))
 def test_round_per_line(self): self.assertEqual(checkout([{'price':'0.005','quantity':1}]*2),Decimal('0.02'))
 def test_empty(self): self.assertEqual(checkout([],0,'1.005'),Decimal('1.01'))
 def test_invalid_price(self):
  for p in ('-1','NaN','Infinity','bad'):
   with self.assertRaises(ValueError): line_total(p,1)
 def test_invalid_quantity(self):
  for q in (-1,1.5,True,'2'):
   with self.assertRaises(ValueError): line_total('1',q)
 def test_invalid_discount(self):
  for d in (-1,101,'NaN','Infinity','bad'):
   with self.assertRaises(ValueError): line_total('1',1,d)
   with self.assertRaises(ValueError): checkout([],d)
 def test_invalid_shipping(self):
  for s in ('-1','NaN','Infinity','bad'):
   with self.assertRaises(ValueError): checkout([],shipping=s)
 def test_full_discount(self): self.assertEqual(line_total('1.2',5,100),Decimal('0.00'))
 def test_input_unchanged(self):
  x=[{'price':'3.75','quantity':2}]; checkout(x,10); self.assertEqual(x,[{'price':'3.75','quantity':2}])
'''
    },
    {
        'id': 'javascript_concurrency',
        'language': 'javascript',
        'files': {'mapLimit.js': '''async function mapLimit(items, limit, mapper) {
  const results = [];
  await Promise.all(items.map(async (item, i) => {
    results.push(await mapper(item, i));
  }));
  return results;
}
module.exports = { mapLimit };
''', 'README.txt': '''Fix async mapLimit(items, limit, mapper). At most limit mapper calls may be active simultaneously. Resolve to results in INPUT order, even if calls finish out of order. Pass (item,index) to mapper and process each item exactly once. Accept sync or async mapper. Empty input resolves to []. Invalid limits (not positive integer, including NaN/Infinity) reject with RangeError, even for empty input. Non-function mapper rejects with TypeError. Mapper exceptions reject the returned promise; after a failure is observed, launch no further items. Do not mutate inputs. Keep CommonJS exports. No dependencies.'''
        },
        'tests': '''const {test}=require('node:test');const assert=require('node:assert/strict');const {mapLimit}=require('./mapLimit');
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
test('concurrency and order',async()=>{let active=0,peak=0;const seen=[];const result=await mapLimit([1,2,3,4,5],2,async(x,i)=>{active++;peak=Math.max(peak,active);seen.push(i);await sleep((6-x)*3);active--;return x*2;});assert.equal(peak,2);assert.deepEqual(result,[2,4,6,8,10]);assert.deepEqual(seen.sort(),[0,1,2,3,4]);});
test('sync mapper and input',async()=>{const a=Object.freeze([2,4,6]);assert.deepEqual(await mapLimit(a,9,(x,i)=>x+i),[2,5,8]);});
test('empty',async()=>assert.deepEqual(await mapLimit([],2,x=>x),[]));
test('invalid limit',async()=>{for(const n of [0,-1,1.5,NaN,Infinity,'2'])await assert.rejects(mapLimit([],n,x=>x),RangeError);});
test('invalid mapper',async()=>assert.rejects(mapLimit([1],1,null),TypeError));
test('stop after rejection',async()=>{const calls=[];await assert.rejects(mapLimit([0,1,2,3],1,async(x)=>{calls.push(x);throw Error('boom');}),/boom/);await sleep(5);assert.deepEqual(calls,[0]);});
test('async rejection',async()=>assert.rejects(mapLimit([1,2],2,async()=>{await sleep(2);throw Error('async failure')}),/async failure/));
'''
    },
]

TOOL_PROBES = [
    {'id':'read_before_edit','prompt':'Before making any edits, read the file src/config.py with read_file. Do not guess its contents.', 'tool':'read_file','args':{'path':'src/config.py'}},
    {'id':'search_symbol','prompt':'Find every definition of normalize_user using search_code with query exactly normalize_user. Do not modify any files yet.', 'tool':'search_code','args':{'query':'normalize_user'}},
    {'id':'run_tests','prompt':'Run the project test suite now using run_tests with no arguments, then wait for the result.', 'tool':'run_tests','args':{}},
]
