from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
CENT=Decimal('0.01')
def number(value,maximum=None):
 try:d=Decimal(str(value))
 except (InvalidOperation,ValueError,TypeError):raise ValueError('invalid number')
 if not d.is_finite() or d<0 or maximum is not None and d>maximum:raise ValueError('range')
 return d
def line_total(price, quantity, discount_percent=0):
 p=number(price);d=number(discount_percent,Decimal(100))
 if isinstance(quantity,bool) or not isinstance(quantity,int) or quantity<0:raise ValueError('quantity')
 return (p*quantity*(Decimal(1)-d/100)).quantize(CENT,rounding=ROUND_HALF_UP)
