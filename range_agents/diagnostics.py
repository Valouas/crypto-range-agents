"""Ex-post diagnostics are labels, NEVER inputs available at signal time."""
from __future__ import annotations
from bisect import bisect_left,bisect_right
from copy import deepcopy
from collections import defaultdict
import numpy as np
from .engine import Simulator

def trajectories(signals,events,horizons_seconds):
 by=defaultdict(list)
 for e in events:
  if e.kind=='trade': by[e.symbol].append(e)
 out=[]
 for s in signals:
  es=by[s['symbol']]; times=[e.ts for e in es]
  i=bisect_left(times,s['timestamp_ms']); entry=s['observed_price']
  for horizon in horizons_seconds:
   deadline=s['timestamp_ms']+horizon*1000
   j=bisect_right(times,deadline)
   if i>=len(es) or times[-1]<deadline:
    out.append({'signal_id':s['id'],'horizon_seconds':horizon,'status':'CENSORED'}); continue
   prices=np.array([e.price for e in es[i:j]])
   if not len(prices): continue
   move=s['side']*(prices/entry-1)*100
   out.append({'signal_id':s['id'],'horizon_seconds':horizon,'status':'OBSERVED_UNTIL_HORIZON',
    'last_observation_ms':es[j-1].ts,'label_available_ms':deadline,
    'favorable_pct':max(0.,float(move.max())),'adverse_pct':min(0.,float(move.min())),
    'last_move_pct':float(move[-1]),'time_to_favorable_max_ms':es[i+int(move.argmax())].ts-s['timestamp_ms'],
    'outside_crossings':int(np.count_nonzero(np.diff((prices>s['threshold']).astype(int))))})
 return out

def counterfactuals(signals,events,cfg,max_signals=None):
 from .policy import require_capability
 require_capability('backtest')
 """Independent one-signal accounts, same execution/cost rules, no portfolio sum.
 Both accepted and refused opportunities are evaluated. Caps are explicit.
 """
 signals=[s for s in signals if s['reason']!='agent_disabled']
 cap=max_signals if max_signals is not None else cfg['diagnostics']['max_counterfactuals']
 by=defaultdict(list)
 for e in events: by[e.symbol].append(e)
 out=[]
 for s in signals[:cap]:
  es=by[s['symbol']]; times=[e.ts for e in es]
  stop=s['timestamp_ms']+int(s['params']['max_holding_hours'][s['tf']]*3600000)+cfg['execution']['order_ttl_ms']*2
  i=bisect_left(times,s['timestamp_ms']); j=bisect_right(times,stop)
  local=deepcopy(cfg); local['signal']['deduplicate_symbol_direction']=False
  sim=Simulator(local,start_ms=s['timestamp_ms'],end_ms=stop+1,run_id='shadow_'+s['id'])
  clean=deepcopy(s); clean['id']='shadow_'+s['id']; clean.pop('risk_budget',None)
  if i>=len(es): continue
  sim.process(es[i]); sim.submit_signal(clean)
  sim.run(es[i+1:j])
  rr=sim.result(); executed=rr['trades']
  out.append({'original_signal_id':s['id'],'original_accepted':s['accepted'],'original_reason':s['reason'],
   'status':'CLOSED' if executed else 'CENSORED' if sim.positions else 'NOT_EXECUTED',
   'counterfactual_net_usd':sum(t['net_usd'] for t in executed) if executed else None,
   'counterfactual_net_r':sum(t['net_r'] for t in executed) if executed else None,
   'entry_status':sim.signals[0]['reason'] if sim.signals else 'NO_EVENT',
   'warning':'Independent simulated opportunity, not additive funded portfolio return'})
 return {'rows':out,'total_signals':len(signals),'processed':len(out),'truncated':len(signals)>cap}
