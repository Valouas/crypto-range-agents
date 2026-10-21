from __future__ import annotations
from dataclasses import dataclass, asdict, field
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
import math

@dataclass(frozen=True)
class Event:
 ts: int
 symbol: str
 kind: str='trade'
 price: float=0.
 qty: float=0.
 seq: int=0
 bid: float=0.
 ask: float=0.
 bid_qty: float=0.
 ask_qty: float=0.
 rate: float=0.  # decimal, NOT percentage. Positive: longs pay shorts.
 received_ms: int|None=None
 source: str='fixture'
 def validate(self):
  if self.kind not in ('trade','quote','mark','funding','heartbeat','delist'): raise ValueError('Type evenement inconnu')
  if not isinstance(self.ts,int) or self.ts<0: raise ValueError('Horodatage invalide')
  for k in ('price','qty','bid','ask','bid_qty','ask_qty','rate'):
   if not math.isfinite(getattr(self,k)): raise ValueError('Nombre non fini')
  if self.kind in ('trade','mark','funding') and self.price<=0: raise ValueError('Prix positif requis')
  if self.kind=='trade' and self.qty<=0: raise ValueError('Quantite transaction positive requise')
  if self.kind=='quote' and not 0<self.bid<=self.ask: raise ValueError('Cotations incoherentes')
  if self.received_ms is not None and self.received_ms<self.ts: raise ValueError('Reception anterieure a source')
 def key(self):
  order={'funding':0,'delist':1,'quote':2,'mark':3,'trade':4,'heartbeat':5}
  return self.ts,order[self.kind],self.symbol,self.seq
 def uid(self): return f'{self.source}:{self.symbol}:{self.kind}:{self.ts}:{self.seq}'

@dataclass(frozen=True)
class RangeDef:
 id: str
 symbol: str
 tf: str
 start_ms: int
 known_ms: int
 expiry_ms: int
 lower: float
 upper: float
 bars: int
 width_pct: float
 volatility_pct: float
 width_tr_ratio: float
 touches_high: int
 touches_low: int
 alternations: int
 drift: float
 boundary_shift: float
 score: float
 method: str='horizontal'
 context: dict=field(default_factory=dict)
 def row(self): return asdict(self)

@dataclass
class Episode:
 range: RangeDef
 family: str
 attempts: int=0
 cycle_side: int=0
 break_bucket: int=-1
 rearm_side: int=0
 waiting_rearm: bool=False
 last_signal_ms: int=-10**18
 ended: bool=False
 reason: str=''
 break_ms: int|None=None
 break_price: float|None=None
 excursion_extreme: float|None=None
 excursion_extreme_ms: int|None=None
 raw_reentries: int=0
 last_outside: bool=False

@dataclass
class Position:
 id: str
 signal_id: str
 symbol: str
 tf: str
 agent: str
 side: int
 family: str
 range_id: str
 entry_ms: int
 entry: float
 qty: float
 remaining: float
 planned_risk: float
 stop: float
 initial_stop_pct: float
 params: dict
 fees: float=0.
 funding: float=0.
 gross: float=0.
 best: float=0.
 tp1_done: bool=False
 tp2_done: bool=False
 be_done: bool=False
 mfe_pct: float=0.
 mae_pct: float=0.
 exit_reason: str=''
 filled_risk: float=0.
 legs: list=field(default_factory=list)
 initial_entry_price: float=0.
 initial_stop_price: float=0.
 initial_r_price: float=0.
 trail_active: bool=False

@dataclass
class Order:
 id: str
 symbol: str
 side: int
 qty: float
 remaining: float
 created_ms: int
 due_ms: int
 expires_ms: int
 submit_event: int
 kind: str  # entry or exit
 position_id: str
 signal: dict=field(default_factory=dict)
 reason: str=''
 status: str='PENDING'
 filled: float=0.

@dataclass(frozen=True)
class Rules:
 tick: float=0.01
 qty_step: float=0.00001
 min_qty: float=0.00001
 min_notional: float=5.
 reduce_only_min_exempt: bool=True
 def qty_down(self,v):
  return float((Decimal(str(max(0.,v)))/Decimal(str(self.qty_step))).to_integral_value(rounding=ROUND_FLOOR)*Decimal(str(self.qty_step)))
 def balance(self,v):
  """Normalize arithmetic on quantities already quantized to whole lots."""
  return float(Decimal(str(self.qty_step))*Decimal(round(max(0.,v)/self.qty_step)))
 def price_adverse(self,v,side):
  return float((Decimal(str(v))/Decimal(str(self.tick))).to_integral_value(rounding=ROUND_CEILING if side==1 else ROUND_FLOOR)*Decimal(str(self.tick)))
 def valid(self,q,p,reduce_only=False):
  return q>0 and (reduce_only and self.reduce_only_min_exempt or (q+1e-12>=self.min_qty and q*p+1e-9>=self.min_notional))
