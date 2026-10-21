"""Event-driven, shared-capital simulator. NO exchange order API exists in this package.
Signals act on observed events, never on future extrema. Market orders fill only
on a later event after latency. Fill price/participation remain explicit models.
"""
from __future__ import annotations
from copy import deepcopy
from dataclasses import asdict
from collections import defaultdict
import math
from .config import TF_MS, validate, digest, agent_config, threshold_pct
from .types import Event, RangeDef, Episode, Position, Order
from .ranges import FamilyRegistry
from .universe import Universe, RuleBook
from .policy import require_capability
from .signals import advance_episode, build_signal, signal_settings
from .geometry import effective_stop, trailing_ready, active_targets
from .allocation import order_available, correlation_admission
from .metrics import calendar_account_metrics

EPS=1e-10

class Simulator:
 def __init__(self,cfg:dict,schedules:dict|None=None,start_ms=0,end_ms=10**18,run_id='simulation',excluded_families=None,model_filters=None,correlation_schedule=None):
  validate(cfg)
  if cfg['mode']=='observation_only': raise PermissionError('Observation seule : aucun portefeuille fictif autorisé')
  require_capability('paper' if cfg['mode']=='paper_only' else 'backtest')
  self.cfg=deepcopy(cfg); self.start_ms=start_ms; self.end_ms=end_ms; self.run_id=run_id
  self.initial=float(cfg['risk']['initial_capital_usd']); self.cash=self.initial
  self.positions={}; self.orders={}; self.trades=[]; self.signals=[]; self.order_log=[]
  self.lifecycle=[]; self.equity_log=[]; self.funding_log=[]; self.incidents=[]
  self.prices={}; self.last_trade_ms={}; self.marks={}; self.quotes={}; self.quote_used={}
  self.episodes={}; self.latest_ranges={}; self.range_rows={}; self.family_registry=FamilyRegistry(cfg['range'])
  self.family_attempts=defaultdict(int); self.family_loss=defaultdict(float)
  self.family_ids={}; self.excluded_families=set(excluded_families or [])
  self.schedules={k:sorted(v,key=lambda r:r.known_ms) for k,v in (schedules or {}).items()}
  self.schedule_index=defaultdict(int)
  self.event_no=0; self.now=-1; self.previous_source_seq={}; self.last_uid=None; self.last_payload=None
  self.halted=False; self.peak=self.initial; self.max_dd=0.; self.flip_queue=[]
  self.rules=RuleBook(cfg['execution']); self.universe=Universe(cfg['universe'])
  self.correlation_schedule=sorted(correlation_schedule or [],key=lambda x:x['known_ms'])
  self.correlation_index=0; self.correlation_snapshot=None
  self.models=dict(model_filters or {})
  if self.models and not cfg['learning']['enabled']: raise ValueError('Modèle injecté sans activation explicite')
  if self.models:
   from .learning import LinearFilter
   # A dependency-injected object must not bypass manual approval or integrity.
   for key, model in list(self.models.items()):
    if not isinstance(model,LinearFilter): raise ValueError('Modèle injecté non vérifiable')
    expected_agent=key[-1] if isinstance(key,tuple) else key
    verified=LinearFilter(model.model,require_approval=True)
    if verified.model['agent']!=expected_agent: raise ValueError('Modèle injecté d’une autre stratégie')
    self.models[key]=verified
  # A fitted model is never activated implicitly. Only checksum-verified, manually approved JSON.
  if cfg['learning']['enabled']:
   for name in cfg['agents']:
    for tf in cfg['timeframes']:
     params=agent_config(cfg,name,tf)
     if params.get('model_path'):
      import json
      from pathlib import Path
      from .learning import LinearFilter
      model=LinearFilter(json.loads(Path(params['model_path']).read_text(encoding='utf-8')))
      if model.model['agent']!=name: raise ValueError('Modèle d’une autre stratégie')
      for sym in cfg['symbols']: self.models[(sym,tf,name)]=model
  self._event=None; self._unsafe_entry=False
  self.signal_index={}; self.last_equity_log_ms=-1
  self.stats=defaultdict(int)

 def equity(self):
  return self.cash+sum(p.side*p.remaining*(self.prices.get(p.symbol,p.entry)-p.entry) for p in self.positions.values())

 def reservations(self):
  out={p.id:{'risk':p.planned_risk,'notional':p.remaining*self.prices.get(p.symbol,p.entry),
                  'side':p.side,'family':p.family,'symbol':p.symbol} for p in self.positions.values()}
  for o in self.orders.values():
   if o.kind=='entry' and o.status in ('PENDING','PARTIAL'):
    s=o.signal; slot=out.setdefault(o.position_id,{'risk':s['risk_budget'],'notional':0.,'side':o.side,'family':s['family'],'symbol':o.symbol})
    slot['risk']=max(slot['risk'],s['risk_budget'])
    slot['notional']+=o.remaining*self.prices.get(o.symbol,s['observed_price'])
  return out

 def _incident(self,reason,**extra):
  self.incidents.append({'timestamp_ms':self.now,'reason':reason,**extra}); self.stats[reason]+=1

 def _log_order(self,o,action,**extra):
  self.order_log.append({'timestamp_ms':self.now,'order_id':o.id,'position_id':o.position_id,
                         'symbol':o.symbol,'action':action,'status':o.status,'remaining':o.remaining,**extra})

 def _cancel(self,o,reason):
  if o.status in ('PENDING','PARTIAL'):
   o.status='CANCELLED'; self._log_order(o,reason)
   if o.kind=='entry':
    signal=self.signal_index.get(o.signal.get('id'))
    if signal: signal['execution_status']='PARTIAL_CANCELLED' if o.filled else 'NOT_FILLED_'+reason

 def _active_order(self,pid,kind):
  return next((o for o in self.orders.values() if o.position_id==pid and o.kind==kind and o.status in ('PENDING','PARTIAL')),None)

 def _publish(self,now):
  while self.correlation_index<len(self.correlation_schedule) and self.correlation_schedule[self.correlation_index]['known_ms']<=now:
   self.correlation_snapshot=self.correlation_schedule[self.correlation_index]; self.correlation_index+=1
  for key,sched in self.schedules.items():
   if key[0] not in self.cfg['symbols'] or key[1] not in self.cfg['timeframes']: continue
   i=self.schedule_index[key]
   while i<len(sched) and sched[i].known_ms<=now:
    r=sched[i]; self.latest_ranges[key]=r
    self.family_ids[r.id]=self.family_registry.family(r)
    i+=1
   self.schedule_index[key]=i
  for key,r in sorted(self.latest_ranges.items()):
   ep=self.episodes.get(key)
   if ep and not ep.ended:
    if now>=ep.range.expiry_ms:
     ep.ended=True; ep.reason='expired'
    elif self.family_attempts[ep.family]>=signal_settings(self.cfg,ep.range.tf)['max_breakouts_per_range'] and not ep.cycle_side:
     ep.ended=True; ep.reason='attempts_exhausted'
    elif self.family_loss[ep.family]>=self.initial*self.cfg['risk']['episode_loss_budget_pct']/100:
     ep.ended=True; ep.reason='loss_budget_exhausted'
    if ep.ended:
     self.lifecycle.append({'timestamp_ms':now,'family':ep.family,'range_id':ep.range.id,'action':ep.reason})
     for o in self.orders.values():
      if o.kind=='entry' and o.signal.get('range_id')==ep.range.id: self._cancel(o,'range_'+ep.reason)
   if ep and not ep.ended: continue  # frozen bounds, regardless of new highs
   family=self.family_ids[r.id]
   if family in self.excluded_families or now>=r.expiry_ms or r.known_ms>now: continue
   if self.family_attempts[family]>=signal_settings(self.cfg,r.tf)['max_breakouts_per_range']: continue
   if self.family_loss[family]>=self.initial*self.cfg['risk']['episode_loss_budget_pct']/100: continue
   # Need a previously observed inside price. Avoid buying stale breakouts at startup.
   prev=self.prices.get(r.symbol)
   if prev is None or not r.lower<prev<r.upper: continue
   self.episodes[key]=Episode(r,family,attempts=self.family_attempts[family])
   self.range_rows[r.id]=r.row()
   self.lifecycle.append({'timestamp_ms':now,'family':family,'range_id':r.id,'action':'installed',
                          'warmup_before_partition':r.start_ms<self.start_ms})

 def install_fixture(self,r):
  """Explicit causal fixture/manual structure. Used by tests and supplied-range studies."""
  f=self.family_registry.family(r); self.family_ids[r.id]=f
  self.latest_ranges[(r.symbol,r.tf)]=r; self.episodes[(r.symbol,r.tf)]=Episode(r,f)
  self.range_rows[r.id]=r.row()

 def _signal_price(self,e):
  source=self.cfg['signal']['trigger_source']
  if source=='last' and e.kind=='trade': return e.price
  if source=='mark' and e.kind=='mark': return e.price
  return None

 def _generate(self,e):
  if not self.start_ms<=e.ts<self.end_ms or self._unsafe_entry: return []
  result=[]
  for key,ep in sorted(self.episodes.items(),key=lambda kv:(-TF_MS[kv[0][1]],kv[0][0])):
   if ep.range.tf not in self.cfg['timeframes']: continue
   obs=advance_episode(ep,e,self.cfg,attempts=self.family_attempts[ep.family])
   if obs is None: continue
   if obs['kind']=='breakout': self.family_attempts[ep.family]=ep.attempts
   if obs['kind'] in ('breakout','reintegration'):
    result.append(build_signal(ep,obs,e,self.cfg,self.run_id))
   else:
    self.lifecycle.append({**obs,'family':ep.family,'range_id':ep.range.id,'action':obs['kind']})
  return result

 def _make_signal(self,ep,agent,side,threshold,e):
  # Compatibility helper for explicitly authorized tests, not an alternate detector.
  return build_signal(ep,{'kind':agent,'side':side,'threshold':threshold},e,self.cfg,self.run_id)

 def submit_signal(self,s,ignore_portfolio=False):
  """Validated proposals; also used by independent counterfactual portfolios."""
  if s['id'] in self.signal_index: return self.signal_index[s['id']]
  s=deepcopy(s); self.signals.append(s); self.signal_index[s['id']]=s
  def no(reason): s['reason']=reason; return s
  if self.halted: return no('halted')
  if s['range_known_ms']>self.now or s.get('feature_known_ms',s['timestamp_ms'])>s['timestamp_ms']: return no('future_range_or_features')
  if s.get('feature_snapshot_hash') and digest(s['features'])!=s['feature_snapshot_hash']: return no('features_mutated')
  if s.get('stop_plan') and not s['stop_plan']['valid']: return no(s['stop_plan']['reason'])
  if not s['params']['enabled']: return no('agent_disabled')
  if self.now>s['timestamp_ms']+self.cfg['execution']['order_ttl_ms']: return no('signal_expired')
  maxhold=s['params']['max_holding_hours'][s['tf']]*3600000
  if self.now+maxhold+self.cfg['execution']['order_ttl_ms']>=self.end_ms: return no('partition_end_purge')
  if not self.universe.eligible(s['symbol'],self.now): return no('universe_not_eligible')
  if self._unsafe_entry: return no('data_stale')
  e=self.cfg['execution']; sym=s['symbol']; side=s['side']
  if e['stop_trigger_source']=='mark' or signal_settings(self.cfg,s['tf'])['trigger_source']=='mark':
   if sym not in self.marks or self.now-self.marks[sym][0]>e['max_mark_age_ms']: return no('mark_missing_or_stale')
  if e['require_quotes'] and (sym not in self.quotes or self.now-self.quotes[sym].ts>e['max_quote_age_ms']): return no('quote_missing_or_stale')
  if abs(s['observed_price']/s['threshold']-1)*100>signal_settings(self.cfg,s['tf'])['max_entry_gap_pct']: return no('entry_gap')
  model=self.models.get((sym,s['tf'],s['agent']),self.models.get(s['agent']))
  if model is not None:
   if model.model['validated_before_ms']>self.now: return no('model_not_yet_available')
   decision=model.assess(s['features'],self.now);s['model_decision']=decision
   if not decision['allowed']: return no('learned_filter:'+decision['reason'])
  if any(p.symbol==sym and p.tf==s['tf'] and p.agent==s['agent'] for p in self.positions.values()): return no('agent_already_open')
  if any(o.kind=='entry' and o.status in ('PENDING','PARTIAL') and o.signal.get('symbol')==sym and o.signal.get('tf')==s['tf'] and o.signal.get('agent')==s['agent'] for o in self.orders.values()): return no('agent_pending')
  if self.cfg['signal']['deduplicate_symbol_direction'] and (
    any(p.symbol==sym and p.side==side for p in self.positions.values()) or
    any(o.symbol==sym and o.kind=='entry' and o.side==side and o.status in ('PENDING','PARTIAL') for o in self.orders.values())): return no('duplicate_symbol_direction')
  opp=[p for p in self.positions.values() if p.symbol==sym and p.side!=side]
  if self.cfg['signal']['opposite_policy']=='net_flip':
   for o in self.orders.values():
    if o.symbol==sym and o.kind=='entry' and o.side!=side: self._cancel(o,'opposite_signal')
   if opp:
    for p in opp: self._request_exit(p,p.remaining,'net_flip')
    s['reason']='waiting_opposite_close'; s['execution_status']='WAITING'
    self.flip_queue.append(s['id']); return s
  return self._admit(s)

 def _admit(self,s):
  def no(reason): s['accepted']=False; s['reason']=reason; return s
  r=self.cfg['risk']; e=self.cfg['execution']; sym=s['symbol']; side=s['side']
  if self.halted or self._unsafe_entry: return no('unsafe_at_admission')
  if self.now-s['timestamp_ms']>=e['order_ttl_ms']: return no('signal_expired_at_admission')
  if self.now>=s.get('range_expiry_ms',10**18): return no('range_expired_at_admission')
  model=self.models.get((sym,s['tf'],s['agent']),self.models.get(s['agent']))
  if model is not None:
   s['model_decision']=model.assess(s['features'],self.now)
   if not s['model_decision']['allowed']: return no('model_recheck:'+s['model_decision']['reason'])
  if e['require_quotes'] and (sym not in self.quotes or self.now-self.quotes[sym].ts>e['max_quote_age_ms']): return no('quote_missing_or_stale')
  if (e['stop_trigger_source']=='mark' or signal_settings(self.cfg,s['tf'])['trigger_source']=='mark') and (sym not in self.marks or self.now-self.marks[sym][0]>e['max_mark_age_ms']): return no('mark_missing_or_stale')
  if not self.universe.eligible(sym,self.now): return no('universe_not_eligible')
  if self.now+int(s['params']['max_holding_hours'][s['tf']]*3600000)+e['order_ttl_ms']>=self.end_ms: return no('partition_end_purge')
  eq=self.equity(); base=min(self.initial,eq); budget=base*r['risk_per_trade_pct']/100
  if budget<=0: return no('capital_exhausted')
  reserved=self.reservations()
  if len(reserved)>=r['max_positions']: return no('max_positions')
  if sum(x['risk'] for x in reserved.values())+budget>base*r['max_open_risk_pct']/100+EPS: return no('max_open_risk')
  if sum(x['risk'] for x in reserved.values() if x['side']==side)+budget>base*r['max_same_side_risk_pct']/100+EPS: return no('direction_risk')
  famrisk=sum(x['risk'] for x in reserved.values() if x['family']==s['family'])
  if self.family_loss[s['family']]+famrisk+budget>self.initial*r['episode_loss_budget_pct']/100+EPS: return no('episode_budget')
  quote=self.quotes.get(sym)
  spread=(quote.ask-quote.bid)/((quote.ask+quote.bid)/2)*100 if quote and self.now-quote.ts<=e['max_quote_age_ms'] else e['spread_proxy_pct']
  rules=self.rules.get(sym,self.now)
  execution_observation=s.get('execution_observed_price',s['observed_price'])
  expected=rules.price_adverse(execution_observation*(1+side*(e['slippage_pct']+spread/2)/100),side)
  plan=s.get('stop_plan',{'valid':True,'anchor_price':None,'distance_pct':s['stop_pct']})
  try: stop_price,effective_pct=effective_stop(expected,side,plan,s['params'],rules)
  except ValueError: return no('stop_geometry_at_expected_price')
  s['expected_stop_price']=stop_price;s['expected_stop_pct']=effective_pct
  if (2*e['fee_pct']+2*e['slippage_pct']+spread)/effective_pct>e['max_cost_to_stop']+EPS: return no('cost_to_stop')
  corr=correlation_admission(sym,side,budget,reserved,self.correlation_snapshot,self.now,self.cfg,base)
  s['correlation_diagnostic']=corr
  if not corr['allowed']: return no('correlated_risk_or_unknown_context')
  unit_risk=max(0.,side*(expected-stop_price))+expected*(2*e['fee_pct']+e['slippage_pct']+spread/2)/100+rules.tick
  gross=sum(v['notional'] for v in reserved.values())
  cap=min(base*r['max_gross_multiple']-gross,(eq-gross/r['leverage_limit'])*r['leverage_limit'])
  qty=rules.qty_down(min(budget/unit_risk,max(0.,cap)/expected))
  if not rules.valid(qty,expected): return no('minimum_or_margin')
  actual_risk=qty*unit_risk
  if gross+qty*expected>base*r['max_gross_multiple']+EPS: return no('gross_limit')
  if (gross+qty*expected)/r['leverage_limit']+qty*expected*e['fee_pct']/100>eq+EPS: return no('margin')
  s.update(accepted=True,reason='submitted',execution_status='PENDING',risk_budget=actual_risk,
           desired_qty=qty,expected_price=expected)
  oid=digest([self.run_id,s['id'],'entry'])[:28]; pid='P'+s['id']
  o=Order(oid,sym,side,qty,qty,self.now,self.now+e['latency_ms'],self.now+e['order_ttl_ms'],self.event_no,'entry',pid,s)
  self.orders[oid]=o; self._log_order(o,'submitted')
  return s

 def _request_exit(self,p,qty,reason):
  # Stop/time/net-flip supersede partial TP and cancel all unfilled scale-in quantity.
  for o in self.orders.values():
   if o.position_id==p.id and o.kind=='entry': self._cancel(o,'protect_or_exit')
  existing=self._active_order(p.id,'exit')
  if existing:
   if reason in ('stop','time_exit','net_flip','safety_exit','delisted'):
    existing.remaining=p.remaining; existing.qty=existing.filled+p.remaining; existing.reason=reason
   return
  rules=self.rules.get(p.symbol,self.now); qty=rules.qty_down(min(qty,p.remaining))
  if p.remaining-qty<rules.qty_step/2: qty=p.remaining
  if reason in ('tp1','tp2') and p.remaining-qty>rules.qty_step/2:
   if not rules.valid(rules.qty_down(p.remaining-qty),self.prices.get(p.symbol,p.entry),True):
    qty=p.remaining
    self._incident('runner_merged_minimum',position=p.id,target=reason)
  if not rules.valid(qty,self.prices.get(p.symbol,p.entry),True):
   if reason in ('tp1','tp2'):
    setattr(p,reason+'_done',True); self._incident('partial_target_merged',position=p.id,target=reason); return
   self.halted=True; self._incident('uncloseable_position',position=p.id); return
  oid=digest([self.run_id,p.id,'exit',len(p.legs),self.event_no,reason])[:28]
  e=self.cfg['execution']
  # Protective reductions do not expire: a data outage must not cancel a stop exit.
  o=Order(oid,p.symbol,-p.side,qty,qty,self.now,self.now+e['latency_ms'],10**18,self.event_no,'exit',p.id,reason=reason)
  self.orders[oid]=o; self._log_order(o,'reduce_only_submitted')

 def _fill_price(self,e,side):
  x=self.cfg['execution']; q=self.quotes.get(e.symbol)
  if q and e.ts-q.ts<=x['max_quote_age_ms']:
   raw=q.ask if side==1 else q.bid
  elif x['require_quotes']: return None
  elif e.kind=='trade': raw=e.price*(1+side*x['spread_proxy_pct']/200)
  else: return None
  rules=self.rules.get(e.symbol,e.ts)
  return rules.price_adverse(raw*(1+side*x['slippage_pct']/100),side)

 def _fill_orders(self,e):
  if e.kind not in ('trade','quote'): return
  x=self.cfg['execution']; rules=self.rules.get(e.symbol,e.ts)
  capacity={1:(e.qty*x['participation'] if e.kind=='trade' else e.ask_qty*x['participation']),
            -1:(e.qty*x['participation'] if e.kind=='trade' else e.bid_qty*x['participation'])}
  total_trade=e.qty*x['participation'] if e.kind=='trade' else math.inf
  active=sorted([o for o in self.orders.values() if o.symbol==e.symbol and o.status in ('PENDING','PARTIAL')],key=lambda o:(o.kind!='exit',o.created_ms,o.id))
  for o in active:
   if self.event_no<=o.submit_event or e.ts<o.due_ms: continue
   if o.kind=='entry' and (self.halted or e.ts>=o.expires_ms): self._cancel(o,'expired_or_halted'); continue
   fill=self._fill_price(e,o.side)
   if fill is None: continue
   if o.kind=='entry':
    if not self.universe.eligible(o.symbol,e.ts): self._cancel(o,'universe_changed'); continue
    if self._unsafe_entry: self._cancel(o,'stale_data'); continue
    if e.ts>=o.signal.get('range_expiry_ms',10**18): self._cancel(o,'range_expired'); continue
    if (x['stop_trigger_source']=='mark' or signal_settings(self.cfg,o.signal['tf'])['trigger_source']=='mark') and (o.symbol not in self.marks or e.ts-self.marks[o.symbol][0]>x['max_mark_age_ms']):
     self._cancel(o,'mark_stale_before_fill'); continue
    if abs(fill/o.signal['threshold']-1)*100>signal_settings(self.cfg,o.signal['tf'])['max_entry_gap_pct']:
     self._cancel(o,'fill_gap'); continue
   qty=min(o.remaining,capacity[o.side],total_trade)
   quote=self.quotes.get(e.symbol)
   if quote and e.ts-quote.ts<=x['max_quote_age_ms']:
    available=(quote.ask_qty if o.side==1 else quote.bid_qty)*x['participation']-self.quote_used.get((e.symbol,o.side),0.)
    qty=min(qty,max(0.,available))
   if o.kind=='exit':
    p=self.positions.get(o.position_id)
    if p is None: self._cancel(o,'position_already_closed'); continue
    qty=min(qty,p.remaining)
   else:
    # Recheck risk at the actual fill, allowing partial reduction, never upsizing.
    p=self.positions.get(o.position_id)
    plan=o.signal.get('stop_plan',{'valid':True,'anchor_price':None,'distance_pct':o.signal['stop_pct']})
    try:
     stop=p.stop if p else effective_stop(fill,o.side,plan,o.signal['params'],rules)[0]
    except ValueError:
     self._cancel(o,'fill_stop_geometry_invalid'); continue
    if o.side*(fill-stop)<=0:
     self._cancel(o,'stop_crossed_before_scale_in'); continue
    risk_existing=getattr(p,'filled_risk',0.) if p else 0.
    unit=max(0.,o.side*(fill-stop))+fill*(2*x['fee_pct']+x['slippage_pct']+x['spread_proxy_pct']/2)/100+rules.tick
    reserved=self.reservations(); own=reserved.get(o.position_id,{'risk':0.,'notional':0.})
    other_risk=sum(v['risk'] for v in reserved.values())-own['risk']
    eq=self.equity();base=min(eq,self.initial);r=self.cfg['risk']
    budget=min(o.signal['risk_budget'],max(0.,base*r['max_open_risk_pct']/100-other_risk))
    qty=min(qty,max(0.,budget-risk_existing)/max(unit,1e-12))
    live_gross=sum(p.remaining*self.prices.get(p.symbol,p.entry) for p in self.positions.values())
    other_pending=sum(oo.remaining*self.prices.get(oo.symbol,oo.signal['observed_price']) for oo in self.orders.values() if oo.id!=o.id and oo.kind=='entry' and oo.status in ('PENDING','PARTIAL'))
    cap=min(base*r['max_gross_multiple']-live_gross-other_pending,eq*r['leverage_limit']-live_gross-other_pending)
    qty=min(qty,max(0.,cap)/(fill*(1+x['fee_pct']/100*r['leverage_limit'])))
   qty=rules.qty_down(qty)
   if qty<=0: continue
   # Exchange constraints apply to the ORDER; a partial fill may be below minimum.
   capacity[o.side]-=qty; total_trade-=qty
   if quote and e.ts-quote.ts<=x['max_quote_age_ms']: self.quote_used[(e.symbol,o.side)]=self.quote_used.get((e.symbol,o.side),0.)+qty
   if o.kind=='entry': self._entry_fill(o,qty,fill,e.ts)
   else: self._exit_fill(o,qty,fill,e.ts)
   o.remaining=rules.balance(o.remaining-qty); o.filled=rules.balance(o.filled+qty)
   if o.remaining<rules.qty_step/2:
    o.remaining=0.; o.status='FILLED'
   else: o.status='PARTIAL'
   self._log_order(o,'fill',quantity=qty,price=fill)
   if o.kind=='entry':
    signal=self.signal_index[o.signal['id']]; signal['execution_status']=o.status
   elif o.status=='FILLED' and o.position_id in self.positions:
    p=self.positions[o.position_id]
    if o.reason in ('tp1','tp2'): setattr(p,o.reason+'_done',True)

 def _entry_fill(self,o,qty,fill,now):
  s=o.signal; e=self.cfg['execution']; fee=qty*fill*e['fee_pct']/100; self.cash-=fee
  p=self.positions.get(o.position_id); rules=self.rules.get(o.symbol,now)
  if p is None:
   plan=s.get('stop_plan',{'valid':True,'anchor_price':None,'distance_pct':s['stop_pct']})
   stop,pct=effective_stop(fill,o.side,plan,s['params'],rules)
   p=Position(o.position_id,s['id'],o.symbol,s['tf'],s['agent'],o.side,s['family'],s['range_id'],now,fill,qty,qty,
              s['risk_budget'],stop,pct,deepcopy(s['params']),fees=fee,best=fill)
   p.initial_entry_price=fill;p.initial_stop_price=stop;p.initial_r_price=abs(fill-stop)
   p.tp1_done=p.params['tp1_fraction']==0;p.tp2_done=p.params['tp2_fraction']==0
   p.filled_risk=qty*(max(0,o.side*(fill-stop))+fill*(2*e['fee_pct']+e['slippage_pct']+e['spread_proxy_pct']/2)/100+rules.tick)
   self.positions[p.id]=p
  else:
   p.entry=(p.entry*p.qty+qty*fill)/(p.qty+qty); p.qty=rules.balance(p.qty+qty); p.remaining=rules.balance(p.remaining+qty); p.fees+=fee
   p.filled_risk+=qty*(max(0,o.side*(fill-p.stop))+fill*(2*e['fee_pct']+e['slippage_pct']+e['spread_proxy_pct']/2)/100+rules.tick)
  # Protection exists for every filled fraction, independent of parent remainder.
  p.legs.append({'timestamp_ms':now,'reason':'entry','qty':qty,'price':fill,'fee':fee,'gross':0.})
  self.stats['entry_fills']+=1

 def _exit_fill(self,o,qty,fill,now):
  p=self.positions[o.position_id]
  move=p.side*(fill/p.entry-1)*100
  p.mfe_pct=max(p.mfe_pct,move); p.mae_pct=min(p.mae_pct,move)
  qty=min(qty,p.remaining); fee=qty*fill*self.cfg['execution']['fee_pct']/100
  gross=p.side*qty*(fill-p.entry)
  self.cash+=gross-fee; p.gross+=gross; p.fees+=fee; p.remaining=self.rules.get(p.symbol,now).balance(p.remaining-qty)
  p.legs.append({'timestamp_ms':now,'reason':o.reason,'qty':qty,'price':fill,'fee':fee,'gross':gross})
  self.stats['exit_fills']+=1
  if p.remaining<=1e-10:
   net=p.gross-p.fees-p.funding
   self.family_loss[p.family]+=max(0.,-net)
   row=asdict(p); row.update(exit_ms=now,net_usd=net,net_r=net/max(getattr(p,'filled_risk',p.planned_risk),1e-12),
     filled_risk_usd=getattr(p,'filled_risk',p.planned_risk),exit_reason=o.reason,holding_hours=(now-p.entry_ms)/3600000)
   self.trades.append(row); del self.positions[p.id]

 def _fund(self,e):
  if self.cfg['execution']['funding_mode']!='historical': return
  for p in self.positions.values():
   if p.symbol!=e.symbol or p.entry_ms>=e.ts: continue
   debit=p.side*p.remaining*e.price*e.rate
   self.cash-=debit; p.funding+=debit
   self.funding_log.append({'timestamp_ms':e.ts,'position_id':p.id,'side':p.side,'rate_decimal':e.rate,'debit_usd':debit})

 def _protect(self,e):
  for p in list(self.positions.values()):
   if p.symbol!=e.symbol and e.kind!='heartbeat': continue
   if e.kind=='delist': self._request_exit(p,p.remaining,'delisted'); self.halted=True; continue
   if e.kind=='trade':
    move=p.side*(e.price/p.entry-1)*100
    p.mfe_pct=max(p.mfe_pct,move); p.mae_pct=min(p.mae_pct,move)
   trigger_source=self.cfg['execution']['stop_trigger_source']
   stop_observed=e.price if (trigger_source=='last' and e.kind=='trade') or (trigger_source=='mark' and e.kind=='mark') else None
   if stop_observed is not None and p.side*(stop_observed-p.stop)<=0:
    self._request_exit(p,p.remaining,'stop'); continue
   if self.now-p.entry_ms>=p.params['max_holding_hours'][p.tf]*3600000:
    self._request_exit(p,p.remaining,'time_exit'); continue
   if e.kind!='trade': continue
   px=e.price; move=p.side*(px/p.entry-1)*100
   p.mfe_pct=max(p.mfe_pct,move); p.mae_pct=min(p.mae_pct,move)
   p.best=max(p.best,px) if p.side==1 else min(p.best,px)
   if self._active_order(p.id,'exit'): continue
   rules=self.rules.get(p.symbol,e.ts)
   be=p.params['breakeven_trigger_pct']
   if be is not None and move>=be: p.be_done=True
   if p.be_done:
    # Whole-trade break-even incl. already realized partials, fees, funding,
    # and estimated remaining execution costs. This is not a price guarantee.
    fee=self.cfg['execution']['fee_pct']/100
    desired=(p.side*p.remaining*p.entry-p.gross+p.fees+p.funding)/(p.remaining*(p.side-fee))
    adverse=(self.cfg['execution']['slippage_pct']+self.cfg['execution']['spread_proxy_pct']/2)/100
    stop=desired/(1-p.side*adverse)
    stop=rules.price_adverse(stop,-p.side)
    p.stop=max(p.stop,stop) if p.side==1 else min(p.stop,stop)
   completed={name for name,_,_ in active_targets(p.params) if getattr(p,name+'_done')}
   initial_move_r=p.side*(px-p.initial_entry_price)/max(p.initial_r_price,1e-12)
   if trailing_ready(p.params,move,initial_move_r,completed): p.trail_active=True
   if p.trail_active:
    trail=rules.price_adverse(p.best*(1-p.side*p.params['runner_trail_pct']/100),-p.side)
    p.stop=max(p.stop,trail) if p.side==1 else min(p.stop,trail)
   # For mark stops, never silently substitute a trade to trigger new protection.
   recheck=px if trigger_source=='last' else (self.marks[p.symbol][1] if p.symbol in self.marks and e.ts-self.marks[p.symbol][0]<=self.cfg['execution']['max_mark_age_ms'] else None)
   if recheck is not None and p.side*(recheck-p.stop)<=0:
    self._request_exit(p,p.remaining,'stop'); continue
   if p.params['tp1_fraction']>0 and not p.tp1_done and move>=p.params['tp1_pct']:
    self._request_exit(p,p.qty*p.params['tp1_fraction'],'tp1')
   elif p.params['tp2_fraction']>0 and not p.tp2_done and move>=p.params['tp2_pct']:
    # A TP1 below minimum is carried into TP2, preserving the original runner.
    exited=p.qty-p.remaining
    qty=max(0.,p.qty*(p.params['tp1_fraction']+p.params['tp2_fraction'])-exited)
    self._request_exit(p,qty,'tp2')

 def check_invariants(self):
  if not math.isfinite(self.cash): raise AssertionError('Non-finite cash')
  for p in self.positions.values():
   if not 0<p.remaining<=p.qty+1e-8 or not math.isfinite(p.stop) or p.stop<=0: raise AssertionError('Protection/quantity invalid')
   if p.planned_risk<=0: raise AssertionError('Risk must be reserved')
  for o in self.orders.values():
   if o.remaining<-EPS: raise AssertionError('Negative order quantity')
   if o.kind=='exit' and o.status in ('PENDING','PARTIAL') and o.position_id in self.positions:
    if o.remaining>self.positions[o.position_id].remaining+1e-8: raise AssertionError('Reduce-only exceeds remaining position')
  # Realized accounting must reconcile, including entry fees of open positions.
  gross=sum(t['gross'] for t in self.trades)+sum(p.gross for p in self.positions.values())
  fees=sum(t['fees'] for t in self.trades)+sum(p.fees for p in self.positions.values())
  funding=sum(t['funding'] for t in self.trades)+sum(p.funding for p in self.positions.values())
  if abs(self.cash-(self.initial+gross-fees-funding))>max(1e-7,abs(self.cash)*1e-10): raise AssertionError('Ledger mismatch')
  return True

 def process(self,e:Event):
  if e.source=='fixture' or 'synthetic' in e.source.lower(): require_capability('synthetic_market')
  e.validate(); uid=e.uid(); payload=digest(asdict(e))
  if uid==self.last_uid:
   if payload!=self.last_payload: raise ValueError('Duplicate ID with different payload')
   self.stats['duplicates_ignored']+=1; return False
  if e.ts<self.now: raise ValueError('Out-of-order event: replay must sort; live uses reception time')
  sk=(e.source,e.symbol,e.kind)
  if e.seq>0 and sk in self.previous_source_seq and e.seq<=self.previous_source_seq[sk]:
   self.stats['old_events_ignored']+=1; return False
  if e.seq>0: self.previous_source_seq[sk]=e.seq
  self.last_uid=uid; self.last_payload=payload
  oldnow=self.now; self.now=e.ts; self.event_no+=1; self._event=e
  self._unsafe_entry=False
  self._publish(e.ts)  # uses previous observations, never current future bar data
  if e.kind=='trade':
   previous=self.last_trade_ms.get(e.symbol)
   if previous is not None and e.ts-previous>self.cfg['execution']['max_trade_gap_ms']:
    self._unsafe_entry=True; self._incident('trade_gap',symbol=e.symbol,gap_ms=e.ts-previous)
    for ep in self.episodes.values():
     if ep.range.symbol==e.symbol: ep.waiting_rearm=True; ep.rearm_side=ep.cycle_side or 1; ep.cycle_side=0
   self.last_trade_ms[e.symbol]=e.ts; self.prices[e.symbol]=e.price
  elif e.kind=='quote': self.quotes[e.symbol]=e; self.quote_used[(e.symbol,1)]=0.; self.quote_used[(e.symbol,-1)]=0.
  elif e.kind=='mark': self.marks[e.symbol]=(e.ts,e.price)
  elif e.kind=='funding': self._fund(e)
  elif e.kind=='heartbeat':
   for symbol,t in self.last_trade_ms.items():
    if e.ts-t>self.cfg['execution']['max_trade_gap_ms']: self._incident('stale_feed',symbol=symbol)
  if self.cfg['execution']['funding_mode']=='adverse_proxy' and oldnow>=0 and e.ts>oldnow:
   rate=self.cfg['execution']['adverse_funding_pct_per_8h']/100
   for p in self.positions.values():
    debit=p.remaining*self.prices.get(p.symbol,p.entry)*rate*(e.ts-oldnow)/28800000
    p.funding+=debit; self.cash-=debit
  # Expired parent cancels remainder only; existing fraction keeps stop.
  for o in self.orders.values():
   if o.kind=='entry' and e.ts>=o.expires_ms: self._cancel(o,'ttl')
  self._fill_orders(e)
  self._protect(e)
  for sid in list(self.flip_queue):
   s=self.signal_index[sid]
   if e.ts-s['timestamp_ms']>self.cfg['execution']['order_ttl_ms']:
    s['reason']='flip_expired'; self.flip_queue.remove(sid)
   elif not any(p.symbol==s['symbol'] and p.side!=s['side'] for p in self.positions.values()):
    s['execution_observed_price']=self.prices.get(s['symbol'],s['observed_price'])
    s['execution_observed_ms']=e.ts
    if abs(s['execution_observed_price']/s['threshold']-1)*100<=signal_settings(self.cfg,s['tf'])['max_entry_gap_pct']:
     self._admit(s)
    else: s['reason']='flip_gap'
    self.flip_queue.remove(sid)
  for s in order_available(self._generate(e),self.cfg,self.models,e.ts): self.submit_signal(s)
  eq=self.equity(); self.peak=max(self.peak,eq); dd=100*(self.peak-eq)/self.peak if self.peak else 0
  self.max_dd=max(self.max_dd,dd)
  stopdd=self.cfg['risk']['pause_drawdown_pct']
  if eq<=0 or (stopdd is not None and dd>=stopdd):
   if not self.halted: self._incident('equity_safety_halt')
   self.halted=True
   for o in self.orders.values():
    if o.kind=='entry': self._cancel(o,'equity_halt')
   for p in self.positions.values(): self._request_exit(p,p.remaining,'safety_exit')
  # Drawdown checked at EVERY event, chart sampled once/minute for bounded size.
  if e.ts-self.last_equity_log_ms>=60000 or self.event_no==1:
   self.equity_log.append({'timestamp_ms':e.ts,'equity_usd':eq,'cash_usd':self.cash,
     'positions':len(self.positions),'risk_reserved_usd':sum(x['risk'] for x in self.reservations().values()),'gross_notional_usd':sum(x['notional'] for x in self.reservations().values())})
   self.last_equity_log_ms=e.ts
  self.check_invariants(); return True

 def run(self,events):
  for e in events:
   if e.ts>=self.end_ms: break
   self.process(e)
  return self.result()

 def result(self):
  state={'timestamp_ms':max(self.start_ms,self.now),'equity_usd':self.equity(),'cash_usd':self.cash,
    'positions':len(self.positions),'risk_reserved_usd':sum(x['risk'] for x in self.reservations().values()),
    'gross_notional_usd':sum(x['notional'] for x in self.reservations().values())}
  log=self.equity_log+[state] if self.now>=self.start_ms else self.equity_log
  calendar_end=max(self.start_ms+1,self.now+1) if self.end_ms>=10**17 else self.end_ms
  calendar=calendar_account_metrics(log,self.trades,self.initial,self.start_ms,calendar_end,self.cfg['research']['calendar_max_state_age_ms'])
  net=sum(t['net_usd'] for t in self.trades)
  agents={}
  for a in ('breakout','reintegration'):
   for tf in self.cfg['timeframes']:
    ts=[t for t in self.trades if t['agent']==a and t['tf']==tf]
    agents[f'{a}:{tf}']={'trades':len(ts),'net_usd':sum(t['net_usd'] for t in ts),
      'mean_net_r':sum(t['net_r'] for t in ts)/len(ts) if ts else None,
      'episodes':len({t['family'] for t in ts})}
  summary={'scope':'ONE_SHARED_MULTI_ASSET_ACCOUNT','initial_capital_usd':self.initial,
   'cash_usd':self.cash,'equity_usd':self.equity(),'net_closed_usd':net,
   'return_marked_pct':100*(self.equity()/self.initial-1),'max_drawdown_event_pct':self.max_dd,
   'trades':len(self.trades),'open_positions':len(self.positions),
   'censored_positions':len(self.positions),'signals':len(self.signals),
   'rejected_signals':sum(not s['accepted'] for s in self.signals),
   'pending_orders':sum(o.status in ('PENDING','PARTIAL') for o in self.orders.values()),
   'fees_usd':sum(t['fees'] for t in self.trades)+sum(p.fees for p in self.positions.values()),
   'funding_debit_usd':sum(t['funding'] for t in self.trades)+sum(p.funding for p in self.positions.values()),
   'execution':'NEXT_OBSERVED_EVENT_AFTER_LATENCY_MODEL_NOT_ACTUAL_FILLS',
   'rules_kind':self.cfg['execution']['rules_kind'],'funding_mode':self.cfg['execution']['funding_mode'],
   'universe_kind':self.cfg['universe']['kind'],'agents':agents,'stats':dict(self.stats),'calendar':calendar,
   'warning':'No forced favorable close at end; remaining positions are censored, not labelled winners.'}
  return {'summary':summary,'trades':self.trades,'signals':self.signals,'orders':self.order_log,
          'ranges':list(self.range_rows.values()),'lifecycle':self.lifecycle,'equity':log,
          'funding':self.funding_log,'incidents':self.incidents,'open_positions':[asdict(p) for p in self.positions.values()]}
