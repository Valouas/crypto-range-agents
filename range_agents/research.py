"""Chronological research. Descriptive pilots are not failed profitability tests.
Optimization cannot touch portfolio risk, latency, fees or approval controls.
"""
from __future__ import annotations
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from collections import defaultdict
import itertools, json, sqlite3, time
import numpy as np
from .config import digest,validate,agent_config
from .data import utc_ms,atomic_json
from .engine import Simulator
from .ranges import FamilyRegistry
from .policy import require_capability
from .governance import ResearchRegistry
from .allocation import correlation_timeline

ALLOWED={'signal.breakout_pct','signal.reintegration_pct','agent.stop_pct','agent.stop_mode',
 'agent.breakeven_trigger_pct','agent.runner_trail_pct','agent.stop_vol_multiplier',
 'agent.stop_range_fraction','agent.tp1_pct','agent.tp2_pct','exit.profile',
 'agent.trailing_trigger_pct','agent.trailing_trigger_r','agent.trailing_activation',
 'agent.stop_boundary_margin_pct','agent.stop_excursion_margin_pct'}

def folds(cfg):
 a,b=utc_ms(cfg['start']),utc_ms(cfg['end_exclusive']); span=b-a
 dev=a+int(span*cfg['research']['development_fraction']); first=a+int(span*cfg['research']['initial_train_fraction'])
 boundaries=np.linspace(first,dev,cfg['research']['folds']+1,dtype=np.int64)
 return [(a,int(boundaries[i]),int(boundaries[i]),int(boundaries[i+1])) for i in range(len(boundaries)-1)],(dev,b)

EXIT_PROFILES={'partials_reference':(0.4,0.3,0.3,'after_last_target'),
 'one_partial':(0.4,0.,0.6,'after_last_target'),'runner_only':(0.,0.,1.,'price_pct')}

def baseline_exit_profile(params):
 value=(params['tp1_fraction'],params['tp2_fraction'],params['runner_fraction'],params['trailing_activation'])
 for name,profile in EXIT_PROFILES.items():
  if value[3]==profile[3] and all(abs(a-b)<1e-10 for a,b in zip(value[:3],profile[:3])): return name
 return 'unchanged'

def apply_variant(cfg,agent,params):
 c=deepcopy(cfg)
 for key,value in params.items():
  group,name=key.split('.')
  if group=='exit':
   if value=='unchanged': continue
   if value not in EXIT_PROFILES: raise ValueError('Profil de sortie inconnu')
   x,y,z,activation=EXIT_PROFILES[value]
   c['agents'][agent].update(tp1_fraction=x,tp2_fraction=y,runner_fraction=z,trailing_activation=activation)
  elif group=='agent': c['agents'][agent][name]=value
  else:c[group][name]=value
 validate(c);return c


def variants(cfg,agent):
 grid=deepcopy(cfg['research'].get('agent_grids',{}).get(agent,cfg['research']['grid']))
 if any(k not in ALLOWED for k in grid): raise ValueError('Optimization of risk/security not allowed')
 if any(not isinstance(v,list) or not v for v in grid.values()): raise ValueError('Invalid grid')
 def current(k):
  group,name=k.split('.')
  return baseline_exit_profile(cfg['agents'][agent]) if group=='exit' else cfg['agents'][agent][name] if group=='agent' else cfg[group][name]
 baseline={k:current(k) for k in grid}
 if cfg['research']['require_one_factor_at_a_time']:
  specifications=[baseline]
  for k,values in grid.items():
   specifications.extend({**baseline,k:v} for v in values if v!=baseline[k])
 else:
  specifications=[dict(zip(grid,values)) for values in itertools.product(*grid.values())]
 unique={digest(p):p for p in specifications}
 if len(unique)>cfg['research']['max_variants']: raise ValueError('Too many variants')
 return [(digest([agent,p])[:16],p,apply_variant(cfg,agent,p)) for p in unique.values()]


def scoped_config(cfg,tf):
 """Resolve overrides before searching: the reported value must be the used value."""
 c=deepcopy(cfg);c['timeframes']=[tf]
 for name in cfg['agents']:c['agents'][name]=agent_config(cfg,name,tf)
 c['signal']={**cfg['signal'],**cfg.get('signal_timeframe_overrides',{}).get(tf,{})}
 c['signal_timeframe_overrides']={}
 validate(c);return c

def merge_shared_threshold(chosen,tf,name,value):
 key=(tf,name)
 if key in chosen and chosen[key]!=value:return False
 chosen[key]=value;return True

def preflight(cfg,schedules=None,dataset=None):
 fs,holdout=folds(cfg); rows=[]
 for i,(a,b,c,d) in enumerate(fs):
  for agent in cfg['agents']:
   for tf in cfg['timeframes']:
    maxhold=cfg['agents'][agent]['max_holding_hours'][tf]*3600000+cfg['execution']['order_ttl_ms']
    duration=d-c
    possible_upper=int(max(0,d-c-maxhold)//{'4h':14400000,'1d':86400000}[tf]+1)*len(cfg['symbols'])
    families=None
    if schedules is not None:
     registry=FamilyRegistry(cfg['range']); seen=set()
     for key,rr in schedules.items():
      if key[1]!=tf: continue
      for r in rr:
       family=registry.family(r)
       if r.expiry_ms>c and r.known_ms<d-maxhold: seen.add(family)
     families=len(seen)
     possible_upper=min(possible_upper,families)
    needed=cfg['research']['min_validation_episodes']
    trade_upper=possible_upper*cfg['signal']['max_breakouts_per_range']
    block_upper=int((d-1)//(cfg['research']['block_days']*86400000)-c//(cfg['research']['block_days']*86400000)+1)
    rows.append({'fold':i,'agent':agent,'tf':tf,'validation_days':duration/86400000,
     'episode_upper_bound':possible_upper,'candidate_families':families,'required_episodes':needed,
     'trade_upper_bound':trade_upper,'calendar_block_upper_bound':block_upper,
     'status':'INSUFFICIENT_POSSIBLE_EPISODES' if possible_upper<needed or duration<=maxhold else ('INSUFFICIENT_POSSIBLE_TRADES' if trade_upper<cfg['research']['min_validation_trades'] else ('INSUFFICIENT_TIME_BLOCKS' if block_upper<cfg['research']['min_validation_blocks'] else 'NOT_PROVEN_IMPOSSIBLE'))})
 warnings=[]
 if cfg['research']['purpose']=='smoke_descriptive': warnings.append('DESCRIPTIVE_PILOT_NO_PROMOTION: this six-month test is not an adequate proof of Daily edge.')
 if cfg['universe']['kind']=='static_exploratory': warnings.append('STATIC_UNIVERSE_NOT_HISTORICAL_TOP50')
 if cfg['execution']['funding_mode']!='historical': warnings.append('HISTORICAL_FUNDING_NOT_MODELLED')
 if cfg['execution']['rules_kind']!='VERIFIED_HISTORICAL_RULES': warnings.append('EXCHANGE_RULES_ARE_HYPOTHESES')
 coverage=dataset.coverage(utc_ms(cfg['start']),utc_ms(cfg['end_exclusive'])) if dataset else []
 return {'rows':rows,'warnings':warnings,'coverage':coverage,
  'holdout':{'start_ms':holdout[0],'end_ms':holdout[1],'opened':False},
  'logic':'Warmup can precede partitions; trade outcomes cannot overlap. Upper bounds are not actual trades.'}

def block_stats(trades,cfg):
 require_capability('backtest')  # includes a stochastic uncertainty diagnostic, never observation-only
 r=cfg['research']; groups=defaultdict(list)
 for t in trades:
  groups[int(t['entry_ms']//(r['block_days']*86400000))].append(t['net_r'])
 values=np.array([np.mean(v) for _,v in sorted(groups.items())],float)
 lower=None
 if len(values)>=2:
  rng=np.random.default_rng(20260921)
  boot=np.mean(rng.choice(values,size=(r['bootstrap_samples'],len(values)),replace=True),axis=1)
  lower=float(np.quantile(boot,0.05))
 return {'trades':len(trades),'episodes':len({t['family'] for t in trades}),'time_blocks':len(values),
  'net_usd':sum(t['net_usd'] for t in trades),
  'mean_net_r':float(np.mean([t['net_r'] for t in trades])) if trades else None,
  'equal_time_block_mean_r':float(values.mean()) if len(values) else None,
  'bootstrap_5pct_diagnostic':lower,
  'uncertainty_warning':'Diagnostic block bootstrap, not a multiple-testing-adjusted significance claim.'}

def calendar_reasons(summary,label):
 """Closed profitable trades alone cannot validate an incomplete/negative account."""
 reasons=[]; cal=summary.get('calendar',{})
 if cal.get('status')!='CALENDAR_COMPLETE':reasons.append(label+'_calendar_incomplete')
 value=cal.get('total_marked_return_pct')
 if value is None or value<=0:reasons.append(label+'_calendar_nonpositive')
 if summary.get('open_positions',0):reasons.append(label+'_unresolved_positions')
 if summary.get('pending_orders',0):reasons.append(label+'_unresolved_orders')
 return reasons

def admissible(train,val,cfg):
 r=cfg['research']; reasons=[]
 for label,data in [('train',train),('validation',val)]:
  if data['trades']<r['min_'+label+'_trades']: reasons.append(label+'_trades_insufficient')
  if data['episodes']<r['min_'+label+'_episodes']: reasons.append(label+'_episodes_insufficient')
  if data['mean_net_r'] is None or data['mean_net_r']<=0: reasons.append(label+'_mean_nonpositive')
 if val['time_blocks']<r['min_validation_blocks']: reasons.append('time_blocks_insufficient')
 if val['bootstrap_5pct_diagnostic'] is None or val['bootstrap_5pct_diagnostic']<=0: reasons.append('bootstrap_diagnostic_not_positive')
 return reasons

def run_partition(dataset,cfg,schedules,a,b,run_id,excluded=None,*,final_opened=False):
 require_capability('backtest')
 if not final_opened:
  with ResearchRegistry() as registry: registry.record_access(dataset.fingerprint,a,b,'development',run_id)
 sim=Simulator(cfg,schedules,a,b,run_id,excluded,
               correlation_schedule=correlation_timeline(dataset.structures,cfg['allocation']))
 return sim.run(dataset.events(a,b))

def research(dataset,cfg,out):
 require_capability('backtest')
 if cfg['mode']!='research_only': raise PermissionError('Configurer explicitement research_only après autorisation')
 registry=ResearchRegistry()
 hypothesis={'id':'range-v3-'+digest(cfg)[:20],
  'change':'One factor per variant' if cfg['research']['require_one_factor_at_a_time'] else 'Explicit multifactor search',
  'baseline':'Unfiltered strategy, fixed shared risk, original partial-exit reference',
  'scope':cfg['symbols'],'metrics':['calendar_net_return','event_drawdown','costs','R_distribution','concentration'],
  'config_hash':digest(cfg)}
 registry.register_hypothesis(hypothesis)
 fs,ho=folds(cfg)
 registry.reserve_holdout('holdout-'+digest([cfg['start'],cfg['end_exclusive'],cfg['research']]),*ho,hypothesis)
 experiment_id=digest([time.time_ns(),dataset.fingerprint,digest(cfg)])[:24]
 code_hash=digest({p.name:p.read_text(encoding='utf-8') for p in Path(__file__).parent.glob('*.py')})
 registry.start_experiment(experiment_id,hypothesis['id'],dataset.fingerprint,code_hash,digest(cfg),fs[0][0],ho[0])
 try:
  result=_research_impl(dataset,cfg,out,registry,experiment_id)
  registry.append_result(experiment_id,'COMPLETED',{'status':result['status'],'trials':result.get('trials_explored',0)})
  return result
 except BaseException as exc:
  registry.append_result(experiment_id,'INTERRUPTED' if isinstance(exc,KeyboardInterrupt) else 'FAILED',{'error':type(exc).__name__+': '+str(exc)})
  raise
 finally:registry.close()


def _research_impl(dataset,cfg,out,registry,experiment_id):
 out=Path(out); out.mkdir(parents=True,exist_ok=True)
 schedule=dataset.schedule(); pf=preflight(cfg,schedule,dataset); atomic_json(out/'preflight.json',pf)
 if any(x['missing_intervals'] for x in pf['coverage']):
  report={'status':'DATA_INCOMPLETE','preflight':pf,'proposals':[],
    'message':'No optimization on a silently truncated event period.'}
  atomic_json(out/'proposals.json',report); return report
 fs,ho=folds(cfg); trials=[]; selected={}; base=deepcopy(cfg)
 study={'config_hash':digest(cfg),'dataset_fingerprint':dataset.fingerprint,'state':'RUNNING','holdout_opened':False}
 atomic_json(out/'study.json',study)
 for agent in cfg['agents']:
  for tf in cfg['timeframes']:
   identity=agent+':'+tf; candidates=[]
   for vid,params,local in variants(scoped_config(cfg,tf),agent):
    # Pool symbols for this family/timeframe, not one almost-empty model per coin.
    local['timeframes']=[tf]
    for name in local['agents']: local['agents'][name]['enabled']=name==agent
    eligible=True; per_fold=[]
    for k,(a,b,c,d) in enumerate(fs):
     train=run_partition(dataset,local,schedule,a,b,f'{identity}-{vid}-train-{k}')
     used={s['family'] for s in train['signals']}
     val=run_partition(dataset,local,schedule,c,d,f'{identity}-{vid}-validation-{k}',used)
     ts=block_stats(train['trades'],cfg); vs=block_stats(val['trades'],cfg)
     reasons=admissible(ts,vs,cfg)+calendar_reasons(train['summary'],'train')+calendar_reasons(val['summary'],'validation')
     if reasons: eligible=False
     per_fold.append({'fold':k,'train':ts,'validation':vs,'reasons':reasons,
                       'train_open_positions':train['summary']['open_positions'],
                       'validation_open_positions':val['summary']['open_positions'],
                       'train_calendar':train['summary']['calendar'],'validation_calendar':val['summary']['calendar']})
    calendar_values=[f['validation_calendar']['total_marked_return_pct'] for f in per_fold]
    if any(v is None for v in calendar_values):eligible=False
    score=float(np.median([v if v is not None else -999. for v in calendar_values]))
    row={'identity':identity,'variant_id':vid,'parameters':params,'folds':per_fold,'score':score,'eligible_diagnostic':eligible}
    candidates.append((row,local)); trials.append(row)
    registry.append_result(experiment_id,'TRIAL',row)
    atomic_json(out/'trials.json',trials)  # interruption does not erase the completed trials
    print(f'{identity} {vid}: score={score:.4f}, eligible={eligible}',flush=True)
   for row,_ in candidates:
    near=[v['score'] for v,_ in candidates if sum(v['parameters'][k]!=row['parameters'][k] for k in row['parameters'])==1]
    row['neighbor_median_score']=float(np.median(near)) if near else None
    row['neighbor_worst_score']=min(near) if near else None
   valid=[(row,c) for row,c in candidates if row['eligible_diagnostic']]
   if valid:
    row,local=max(valid,key=lambda pair:(pair[0]['score'],pair[0]['variant_id']))
    selected[identity]={'parameters':row['parameters'],'variant_id':row['variant_id'],'score':row['score']}
 # Build joint portfolio candidate with family-specific timeframes, no hidden capital multiplication.
 for agent in base['agents']:
  for tf in cfg['timeframes']:
   base['agents'][agent].setdefault('timeframe_overrides',{}).setdefault(tf,{})['enabled']=agent+':'+tf in selected
 conflicts=[];shared_thresholds={}
 for identity,v in selected.items():
  agent,tf=identity.split(':')
  overrides=base['agents'][agent].setdefault('timeframe_overrides',{}).setdefault(tf,{})
  for key,value in v['parameters'].items():
   group,name=key.split('.')
   if group=='exit':
    if value!='unchanged':
     overrides.update(zip(('tp1_fraction','tp2_fraction','runner_fraction','trailing_activation'),EXIT_PROFILES[value]))
   elif group=='agent': overrides[name]=value
   else:
    if not merge_shared_threshold(shared_thresholds,tf,name,value):
     conflicts.append({'tf':tf,'parameter':name,'existing':shared_thresholds[(tf,name)],'requested':value,'agent':agent})
    else:base.setdefault('signal_timeframe_overrides',{}).setdefault(tf,{})[name]=value
 joint={'reasons':['INCOMPATIBLE_SHARED_SIGNAL_PARAMETERS'],'conflicts':conflicts} if conflicts else None
 if selected and not conflicts:
  a,b,c,d=fs[-1]
  train=run_partition(dataset,base,schedule,a,b,'joint-training')
  used={s['family'] for s in train['signals']}
  val=run_partition(dataset,base,schedule,c,d,'joint-selected-validation',used)
  stress=deepcopy(base);stress['execution'].update(cfg['research']['stress'])
  adverse=run_partition(dataset,stress,schedule,c,d,'joint-stress-validation',used)
  reasons=admissible(block_stats(train['trades'],cfg),block_stats(val['trades'],cfg),cfg)
  reasons+=calendar_reasons(train['summary'],'joint_train')+calendar_reasons(val['summary'],'joint_validation')
  reasons+=calendar_reasons(adverse['summary'],'joint_stress')
  joint={'base':val['summary'],'stress':adverse['summary'],'reasons':reasons,
         'warning':'Same development validation, not an independent unseen holdout.'}
  atomic_json(out/'joint_validation.json',joint)
 status=('CANDIDATE_REQUIRES_MANUAL_REVIEW' if not joint['reasons'] else 'JOINT_PORTFOLIO_NOT_ADMISSIBLE') if selected else 'NO_ELIGIBLE_CANDIDATE'
 if dataset.manifest.get('synthetic'): status='SYNTHETIC_NO_PROMOTION'
 elif cfg['research']['purpose']=='smoke_descriptive': status='DESCRIPTIVE_NO_PROMOTION'
 proposal={'format':2,'status':status,'synthetic':bool(dataset.manifest.get('synthetic')),
   'dataset_fingerprint':dataset.fingerprint,'base_config':cfg,'candidate_config':base,
   'selections':selected,'joint_validation':joint,'trials_explored':len(trials),'holdout_start_ms':ho[0],'holdout_end_ms':ho[1],
   'holdout_opened':False,'approved':False,'multiple_testing_warning':'All variants recorded. No statistical proof of profitability.'}
 proposal['integrity']=digest(proposal)
 atomic_json(out/'trials.json',trials); atomic_json(out/'proposals.json',proposal)
 study['state']='COMPLETED';study['status']=status;atomic_json(out/'study.json',study)
 return proposal

class StudyLedger(ResearchRegistry):
 def open_once(self,dataset,a,b,proposal):
  return self.claim_holdout(dataset,a,b,proposal)


def check_proposal(p):
 payload={k:v for k,v in p.items() if k!='integrity'}
 if p.get('integrity')!=digest(payload): raise ValueError('Proposal altered; rerun research, do not edit results')
 if p.get('synthetic') or p.get('status')!='CANDIDATE_REQUIRES_MANUAL_REVIEW': raise ValueError('No approvable market-data candidate')

def holdout(dataset,proposal,ledger=None):
 require_capability('backtest')
 check_proposal(proposal)
 if dataset.fingerprint!=proposal['dataset_fingerprint']: raise ValueError('Dataset changed')
 own=ledger is None;ledger=ledger or StudyLedger()
 try:
  a,b=proposal['holdout_start_ms'],proposal['holdout_end_ms']
  ledger.open_once(dataset.fingerprint,a,b,proposal['integrity'])
  c=proposal['candidate_config']; result=run_partition(dataset,c,dataset.schedule(c['range']),a,b,'holdout-'+proposal['integrity'][:12],final_opened=True)
  return {'proposal_integrity':proposal['integrity'],'dataset_fingerprint':dataset.fingerprint,'result':result,
   'warning':'One-time test opened. Retuning after reading it requires new unseen data.'}
 finally:
  if own:ledger.close()

def approve(proposal,ack):
 require_capability('backtest')
 check_proposal(proposal)
 if ack!='APPROUVER_SIMULATION': raise ValueError('Explicit acknowledgement APPROUVER_SIMULATION required')
 return {'config':proposal['candidate_config'],'approval':{'ack':ack,'proposal_integrity':proposal['integrity'],
  'timestamp':int(time.time()),'scope':'SIMULATION_ONLY_NO_LIVE_CONNECTOR'}}

def compare_baseline(dataset,cfg,a,b):
 require_capability('backtest')
 out={}
 for method in ('horizontal','donchian'):
  local=deepcopy(cfg); local['range']['method']=method
  schedules=dataset.schedule(local['range'])
  for policy in ('hedge','net_flip'):
   for scenario in ('base','stress'):
    c=deepcopy(local); c['signal']['opposite_policy']=policy
    if scenario=='stress': c['execution'].update(c['research']['stress'])
    key=f'{method}:{policy}:{scenario}'
    out[key]=run_partition(dataset,c,schedules,a,b,key)
 return out
