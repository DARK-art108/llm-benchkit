from decimal import Decimal, ROUND_HALF_UP
from money import number, line_total, CENT
def checkout(items,discount_percent=0,shipping='0.00'):
 d=number(discount_percent,Decimal(100));s=number(shipping).quantize(CENT,rounding=ROUND_HALF_UP)
 return sum((line_total(i['price'],i['quantity'],d)for i in items),Decimal('0.00'))+s
