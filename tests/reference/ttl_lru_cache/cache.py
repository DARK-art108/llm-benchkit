from collections import OrderedDict
import time
class TTLCache:
 def __init__(self, capacity, clock=time.monotonic):
  if isinstance(capacity,bool) or not isinstance(capacity,int) or capacity<=0: raise ValueError('capacity')
  self.capacity=capacity; self.clock=clock; self.items=OrderedDict()
 def put(self,key,value,ttl):
  now=self.clock()
  for k,(_,expiry) in list(self.items.items()):
   if now>=expiry: del self.items[k]
  self.items.pop(key,None)
  if ttl<=0:return
  self.items[key]=(value,now+ttl)
  while len(self.items)>self.capacity:self.items.popitem(last=False)
 def get(self,key,default=None):
  if key not in self.items:return default
  value,expiry=self.items[key]
  if self.clock()>=expiry:
   del self.items[key];return default
  self.items.move_to_end(key);return value
