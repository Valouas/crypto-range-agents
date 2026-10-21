"""Causal horizontal structures, variable windows, frozen published candidates.
width_tr_ratio uses the median true range (not Wilder ATR). volatility_pct uses
Wilder's ATR(14), evaluated on CLOSED structural bars only.
"""
from __future__ import annotations
from bisect import bisect_right
from dataclasses import replace
from collections import deque
import math
import numpy as np
import pandas as pd
from .config import TF_MS, digest
from .types import RangeDef

def aggregate(minutes: pd.DataFrame,tf: str):
 duration=TF_MS[tf]; x=minutes.copy()
 if x.timestamp_ms.duplicated().any(): raise ValueError('Minutes dupliquees')
 x['bucket']=x.timestamp_ms//duration*duration
 g=x.groupby('bucket',sort=True).agg(open=('open','first'),high=('high','max'),low=('low','min'),close=('close','last'),count=('close','size'),first=('timestamp_ms','min'),last=('timestamp_ms','max'))
 g=g.loc[(g['count']==duration//60000)&(g['first']==g.index)&(g['last']==g.index+duration-60000)]
 g=g.reset_index().rename(columns={'bucket':'timestamp_ms'})
 return g[['timestamp_ms','open','high','low','close']]

def validate_structure(bars,tf):
 cols=['timestamp_ms','open','high','low','close']
 if not set(cols)<=set(bars.columns): raise ValueError('Structure incomplete')
 b=bars[cols].copy()
 if b.empty: return b
 t=b.timestamp_ms.to_numpy(dtype=np.int64)
 if np.any(np.diff(t)<=0) or np.any(t%TF_MS[tf]): raise ValueError('Structure non triee/alignee')
 arr=b[['open','high','low','close']].to_numpy(float)
 if not np.isfinite(arr).all() or (arr<=0).any(): raise ValueError('Prix structure invalides')
 if (b.high<b[['open','close','low']].max(axis=1)).any() or (b.low>b[['open','close','high']].min(axis=1)).any(): raise ValueError('OHLC invalides')
 return b

def wilder_atr(bars,period=14,tf=None):
 if bars.empty: return np.array([])
 h=bars.high.to_numpy(float); l=bars.low.to_numpy(float); c=bars.close.to_numpy(float)
 prev=np.r_[bars.open.iloc[0],c[:-1]]
 tr=np.maximum(h-l,np.maximum(abs(h-prev),abs(l-prev)))
 # Warmup average until period, then Wilder recurrence. No future used.
 out=np.empty(len(tr)); out[0]=tr[0]
 age=1
 for i in range(1,len(tr)):
  if tf is not None and int(bars.timestamp_ms.iloc[i])-int(bars.timestamp_ms.iloc[i-1])!=TF_MS[tf]:
   tr[i]=h[i]-l[i]; out[i]=tr[i]; age=1; continue
  age+=1; n=min(age,period); out[i]=((n-1)*out[i-1]+tr[i])/n
 return out

def _runs(f): return int(np.count_nonzero(f & ~np.r_[False,f[:-1]]))

def evaluate(bars,end,window,symbol,tf,cfg,atr_value):
 a=end-window+1
 if a<0: return None
 p=bars.iloc[a:end+1]
 t=p.timestamp_ms.to_numpy(np.int64)
 if len(t)>1 and np.any(np.diff(t)!=TF_MS[tf]): return None  # don't bridge outages/listing gaps
 h=p.high.to_numpy(float); l=p.low.to_numpy(float); c=p.close.to_numpy(float)
 hi=float(h.max()); lo=float(l.min()); width=hi-lo; mid=(hi+lo)/2
 if width<=0: return None
 width_pct=100*width/mid
 if not cfg['min_width_pct']<=width_pct<=cfg['max_width_pct']: return None
 prev=np.r_[float(p.open.iloc[0]),c[:-1]]
 med=float(np.median(np.maximum(h-l,np.maximum(abs(h-prev),abs(l-prev)))))
 ratio=width/max(med,1e-12)
 band=cfg['touch_band_fraction']*width
 th=h>=hi-band; tl=l<=lo+band
 nh,nl=_runs(th),_runs(tl)
 labels=np.where(th&~tl,1,np.where(tl&~th,-1,0)); nz=labels[labels!=0]
 alt=int(np.count_nonzero(np.diff(nz)))
 x=np.arange(window,dtype=float); xx=x-x.mean()
 slope=float(np.dot(xx,c-c.mean())/max(float(np.dot(xx,xx)),1e-12))
 drift=abs(slope*(window-1))/width
 split=window//2
 shift=max(abs(h[:split].max()-h[split:].max()),abs(l[:split].min()-l[split:].min()))/width
 if cfg['method']=='horizontal' and (ratio<cfg['min_width_tr_ratio'] or min(nh,nl)<cfg['min_distinct_touches'] or alt<cfg['min_alternations'] or drift>cfg['max_drift_fraction'] or shift>cfg['max_boundary_shift_fraction']): return None
 known=int(t[-1])+TF_MS[tf]
 rid=digest([symbol,tf,int(t[0]),known,lo,hi,cfg['method']])[:20]
 score=math.log1p(window)+math.log1p(alt)-drift-shift
 return RangeDef(rid,symbol,tf,int(t[0]),known,known+cfg['expiry_bars'][tf]*TF_MS[tf],lo,hi,window,width_pct,100*atr_value/max(c[-1],1e-12),ratio,nh,nl,alt,drift,shift,score,cfg['method'])

def candidate_windows(bars,end,tf,cfg):
 maximum=min(end+1,cfg['max_bars'][tf]); minimum=cfg['min_bars'][tf]
 if maximum<minimum: return []
 ws={int(w) for w in cfg['lookbacks'][tf] if minimum<=w<=maximum}
 if cfg['adaptive']:
  # Consecutive recent lengths plus durations anchored to pivots confirmed on
  # closed bars. Longest available span is always considered (not fixed to grid).
  ws.update(range(minimum,min(maximum,minimum+7)+1)); ws.add(maximum)
  lo=max(0,end-cfg['max_bars'][tf]+1)
  hh=bars.high.to_numpy(float)[lo:end+1]; ll=bars.low.to_numpy(float)[lo:end+1]
  if len(hh)>=5:
   from numpy.lib.stride_tricks import sliding_window_view
   highs=sliding_window_view(hh,5); lows=sliding_window_view(ll,5)
   pivots=np.flatnonzero((hh[2:-2]>=highs.max(axis=1))|(ll[2:-2]<=lows.min(axis=1)))+lo+2
   ws.update(int(end-j+1) for j in pivots if minimum<=end-j+1<=maximum)
 ws=sorted(ws)
 if len(ws)>cfg['max_candidates']:
  # Sample on index, include extrema and configured long windows. Deterministic.
  idx=np.linspace(0,len(ws)-1,cfg['max_candidates'],dtype=int)
  ws=sorted({ws[i] for i in idx})  # Strict cap; index sample includes the extremes.
 return ws

def _major_levels_at_close(bars,tf,cfg,atr):
 """Yield only unswept pivots confirmed and displaced BEFORE the current close.
 Their scope is the configured structural history, not every historical level.
 """
 left,right=cfg['major_pivot_left'],cfg['major_pivot_right']
 pending=[]; active=[]
 h=bars.high.to_numpy(float);l=bars.low.to_numpy(float);t=bars.timestamp_ms.to_numpy(np.int64)
 for i in range(len(bars)):
  if i and t[i]-t[i-1]!=TF_MS[tf]: pending=[];active=[]
  active=[x for x in active if i-x['pivot_index']<=cfg['max_bars'][tf]
          and not ((x['side']==1 and h[i]>x['price']) or (x['side']==-1 and l[i]<x['price']))]
  next_pending=[]
  for x in pending:
   if i-x['pivot_index']>cfg['max_bars'][tf]: continue
   if (x['side']==1 and h[i]>x['price']) or (x['side']==-1 and l[i]<x['price']): continue
   x['away']=max(x['away'],x['price']-l[i] if x['side']==1 else h[i]-x['price'])
   if x['away']>=x['required']:
    active.append({**x,'known_ms':int(t[i])+TF_MS[tf]})
   else: next_pending.append(x)
  pending=next_pending
  j=i-right
  if j>=left and np.all(np.diff(t[j-left:i+1])==TF_MS[tf]):
   for side,price,is_pivot in ((1,h[j],h[j]>=h[j-left:i+1].max()),
                                (-1,l[j],l[j]<=l[j-left:i+1].min())):
    if not is_pivot: continue
    away=price-float(l[j+1:i+1].min()) if side==1 else float(h[j+1:i+1].max())-price
    x={'pivot_index':j,'side':side,'price':float(price),'away':away,
       'required':float(atr[j])*cfg['major_min_atr'],'known_ms':int(t[i])+TF_MS[tf]}
    (active if away>=x['required'] else pending).append(x)
  yield tuple(dict(x) for x in active)


def _price_context(bars,end,r,cfg,major):
 a=max(0,end-cfg['approach_bars']+1);p=bars.iloc[a:end+1]
 # Do not bridge an absent structural candle while describing the approach.
 if len(p)>1 and np.any(np.diff(p.timestamp_ms.to_numpy(np.int64))!=TF_MS[r.tf]):
  p=bars.iloc[end:end+1]
 closes=p.close.to_numpy(float);width=r.upper-r.lower;band=cfg['touch_band_fraction']*width
 highs=sorted(x['price'] for x in major if x['side']==1 and x['price']>r.upper)
 lows=sorted((x['price'] for x in major if x['side']==-1 and x['price']<r.lower),reverse=True)
 c=float(closes[-1])
 return {'context_known_ms':r.known_ms,'last_closed_price':c,
   'approach_observed_bars':len(p),'approach_net_range_fraction':float((closes[-1]-closes[0])/width),
   'approach_path_range_fraction':float(np.abs(np.diff(closes)).sum()/width),
   'near_high_close_fraction':float(np.mean(closes>=r.upper-band)),
   'near_low_close_fraction':float(np.mean(closes<=r.lower+band)),
   'last_close_range_fraction':(c-r.lower)/width,
   'recent_pullback_from_high_fraction':float((r.upper-p.low.min())/width),
   'recent_pullback_from_low_fraction':float((p.high.max()-r.lower)/width),
   'next_major_high_pct':100*(highs[0]/r.upper-1) if highs else None,
   'next_major_low_pct':100*(1-lows[0]/r.lower) if lows else None,
   'next_major_high_known':int(bool(highs)),'next_major_low_known':int(bool(lows)),
   'major_levels_scope':'CONFIRMED_UNSWEPT_WITHIN_CONFIGURED_HISTORY'}


def iter_candidate_groups(bars,symbol,tf,cfg):
 """Bounded bank per publication. Journal alternatives; keep old score only as reference.
 Appending future bars cannot change an earlier group or any of its features.
 """
 b=validate_structure(bars,tf);atr=wilder_atr(b,tf=tf)
 for i,major in enumerate(_major_levels_at_close(b,tf,cfg,atr)):
  raw=[r for w in candidate_windows(b,i,tf,cfg)
       if (r:=evaluate(b,i,w,symbol,tf,cfg,atr[i])) is not None]
  if not raw: continue
  chosen=sorted(raw,key=lambda r:(r.score,r.bars,r.id),reverse=True)[:cfg['bank_size']]
  out=[]
  for rank,r in enumerate(chosen):
   enclosing=[x for x in chosen if x.id!=r.id and x.lower<=r.lower and x.upper>=r.upper
              and (x.lower<r.lower or x.upper>r.upper)]
   context=_price_context(b,i,r,cfg,major)
   context.update(bank_rank=rank,bank_size=len(chosen),enclosing_candidates=len(enclosing),
    inside_larger_candidate=int(bool(enclosing)),
    outer_upper_distance_pct=min((100*(x.upper/r.upper-1) for x in enclosing),default=None),
    outer_lower_distance_pct=min((100*(1-x.lower/r.lower) for x in enclosing),default=None),
    selection_rule='V2_SCORE_REFERENCE_NOT_ECONOMICALLY_VALIDATED')
   out.append(replace(r,context=context))
  yield out


def build_schedule(bars,symbol,tf,cfg):
 return [group[0] for group in iter_candidate_groups(bars,symbol,tf,cfg)]


def same_family(a:RangeDef,b:RangeDef,cfg):
 if a.symbol!=b.symbol or a.tf!=b.tf: return False
 tol=cfg['family_tolerance_pct']/100
 close=max(abs(a.upper/b.upper-1),abs(a.lower/b.lower-1))<=tol
 overlap=max(0,min(a.known_ms,b.known_ms)-max(a.start_ms,b.start_ms))
 denom=max(1,min(a.known_ms-a.start_ms,b.known_ms-b.start_ms))
 return close and overlap/denom>=cfg['refresh_overlap_fraction']

class FamilyRegistry:
 """Do not reset loss/attempt budgets merely because identical bounds republish."""
 def __init__(self,cfg): self.cfg=cfg; self.items=[]
 def family(self,r):
  for old,fid in reversed(self.items):
   if same_family(old,r,self.cfg):
    self.items.append((r,fid)); return fid
  fid=r.id; self.items.append((r,fid)); return fid
