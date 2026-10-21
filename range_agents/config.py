"""Validated, versioned configuration. *_pct is in percent: 0.1 = 0.1 percent."""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import math
import re

TF_MS = {'4h': 14_400_000, '1d': 86_400_000}
AGENT = dict(enabled=True, stop_pct=0.6, stop_mode='fixed', stop_vol_multiplier=0.8,
             stop_range_fraction=0.06, stop_min_pct=0.05, stop_max_pct=5.0,
             tp1_pct=0.6, tp2_pct=1.2, tp1_fraction=0.4, tp2_fraction=0.3,
             breakeven_trigger_pct=None, runner_trail_pct=0.8,
             max_holding_hours={'4h':72, '1d':120}, model_path=None)
DEFAULT = {
 'schema_version':2, 'mode':'research_only',
 'symbols':['BTCUSDT','ETHUSDT','SOLUSDT'], 'timeframes':['4h','1d'],
 'data_start':'2024-01-01', 'start':'2025-01-01', 'end_exclusive':'2025-07-01',
 'universe':{'kind':'static_exploratory','snapshots_file':None,'max_assets':50},
 'range':{'method':'horizontal','adaptive':True,'max_candidates':32,
  'lookbacks':{'4h':[12,24,48,96,180,360,540,720], '1d':[7,14,30,60,90,120,180]},
  'max_bars':{'4h':720,'1d':180}, 'min_bars':{'4h':12,'1d':7},
  'min_width_pct':0.5,'max_width_pct':60.,'min_width_tr_ratio':2.5,
  'touch_band_fraction':0.15,'min_distinct_touches':2,'min_alternations':3,
  'max_drift_fraction':0.35,'max_boundary_shift_fraction':0.4,
  'expiry_bars':{'4h':24,'1d':14},'family_tolerance_pct':0.15,
  'refresh_overlap_fraction':0.5},
 'signal':{'breakout_pct':0.1,'reintegration_pct':0.05,'breakout_mode':'fixed',
  'breakout_vol_multiplier':0.1,'breakout_range_fraction':0.01,
  'breakout_min_pct':0.01,'breakout_max_pct':1.0,'rearm_pct':0.1,
  'cooldown_ms':300000,'max_breakouts_per_range':2,'same_structure_candle':True,
  'opposite_policy':'hedge','max_entry_gap_pct':0.4,
  'deduplicate_symbol_direction':True,'trigger_source':'last'},
 'agents':{'breakout':deepcopy(AGENT),'reintegration':deepcopy(AGENT)},
 'execution':{'latency_ms':100,'order_ttl_ms':5000,'slippage_pct':0.02,
  'spread_proxy_pct':0.02,'fee_pct':0.05,'participation':0.02,
  'require_quotes':False,'max_quote_age_ms':2000,'max_trade_gap_ms':120000,
  'max_mark_age_ms':5000,'stop_trigger_source':'last','max_cost_to_stop':0.75,
  'funding_mode':'none_unavailable','adverse_funding_pct_per_8h':0.01,
  'rules_kind':'HYPOTHETICAL_NOT_VERIFIED_EXCHANGE_RULES',
  'rules_default':{'tick':0.01,'qty_step':0.00001,'min_qty':0.00001,
                   'min_notional':5.,'reduce_only_min_exempt':True},
  'rules':{},'rule_history_file':None},
 'risk':{'initial_capital_usd':300.,'risk_per_trade_pct':0.25,
  'max_open_risk_pct':1.,'max_positions':3,'max_gross_multiple':2.,
  'leverage_limit':2.,'episode_loss_budget_pct':0.75,
  'max_same_side_risk_pct':0.75,'pause_drawdown_pct':None},
 'research':{'purpose':'smoke_descriptive','development_fraction':0.8,
  'initial_train_fraction':0.4,'folds':3,'min_train_trades':50,
  'min_validation_trades':30,'min_train_episodes':15,'min_validation_episodes':10,
  'min_validation_blocks':6,'block_days':7,'bootstrap_samples':500,
  'max_variants':24,'grid':{'signal.breakout_pct':[0.05,0.1],
         'agent.stop_pct':[0.3,0.6,1.0],'agent.breakeven_trigger_pct':[None,0.6]},
  'stress':{'latency_ms':1000,'slippage_pct':0.08,'spread_proxy_pct':0.06}},
 'diagnostics':{'horizons_seconds':[60,300,900,3600,14400],
                'counterfactual':True,'max_counterfactuals':10000},
}


# V3 reference is observation only. Experimental alternatives remain disabled.
AGENT.update(runner_fraction=0.3, trailing_activation='after_last_target',
             trailing_trigger_pct=1.2, trailing_trigger_r=2.0,
             stop_boundary_margin_pct=0.05, stop_excursion_margin_pct=0.05)
DEFAULT['schema_version']=3
DEFAULT['mode']='observation_only'
for _name in DEFAULT['agents']:
 DEFAULT['agents'][_name]=deepcopy(AGENT)
DEFAULT['signal'].update(reintegration_window='same_candle', max_reintegration_ms=3600000)
DEFAULT['range'].update(bank_size=12, approach_bars=5,
    major_pivot_left=5, major_pivot_right=3, major_min_atr=2.0)
DEFAULT['observation']={'require_verified_archives':True, 'allow_partial_coverage':True,
    'register_viewed_periods':True, 'max_event_silence_ms':120000,
    'horizons_seconds':[60,300,900,3600,14400], 'export_event_catalog':True}
DEFAULT['allocation']={'mode':'sequential',
    'agent_priority':['breakout:1d','reintegration:1d','breakout:4h','reintegration:4h'],
    'correlation_enabled':False, 'correlation_tf':'4h', 'correlation_lookback':60,
    'correlation_min_pairs':30, 'correlation_threshold':0.85,
    'max_correlated_risk_pct':0.75, 'missing_correlation_policy':'diagnostic_only'}
DEFAULT['learning']={'enabled':False,'objective':'ridge_net_r','min_rows':100,
    'min_calibration_rows':30,'min_validation_rows':30, 'min_expected_net_r':0.0,
    'max_disagreement_r':2.0,'ood_quantile':0.99,'max_model_age_days':30,
    'unknown_policy':'abstain','reference_fallback_approved':False,
    'max_calibration_error':0.2,'min_distinct_families':15,'features':None}
DEFAULT['research'].update(selection_metric='calendar_net_return',
    calendar_max_state_age_ms=120000, global_registry_required=True,
    require_one_factor_at_a_time=True)
DEFAULT['diagnostics']['counterfactual']=False


def migrate_v2(old: dict) -> dict:
 """Produce a new observation-only config; never unlock execution or activate alternatives."""
 if old.get('schema_version') != 2: raise ValueError('Seule la configuration V2 est migrable ici.')
 def merge(base, incoming):
  out=deepcopy(base)
  for k,v in incoming.items():
   out[k]=merge(out[k],v) if isinstance(v,dict) and isinstance(out.get(k),dict) else deepcopy(v)
  return out
 c=merge(DEFAULT,old); c['schema_version']=3; c['mode']='observation_only'
 c['learning']['enabled']=False
 for a in c['agents'].values():
  a['runner_fraction']=1-a['tp1_fraction']-a['tp2_fraction']
  a['model_path']=None
  for v in a.get('timeframe_overrides',{}).values():
   if 'tp1_fraction' in v or 'tp2_fraction' in v:
    v['runner_fraction']=1-v.get('tp1_fraction',a['tp1_fraction'])-v.get('tp2_fraction',a['tp2_fraction'])
   if v.get('model_path'): v['model_path']=None
 validate(c); return c

def digest(value: object) -> str:
 return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False,separators=(',',':')).encode()).hexdigest()

def load_config(path: str|Path|None=None) -> dict:
 c=deepcopy(DEFAULT) if path is None else json.loads(Path(path).read_text(encoding='utf-8-sig'))
 if c.get('schema_version') in (1,2):
  raise ValueError('Migration explicite requise : migrate-config. Ne pas remplacer la V2 en place.')
 validate(c); return c


def finite(x, name, lo=0., hi=None):
 if isinstance(x,bool) or not isinstance(x,(float,int)) or not math.isfinite(x) or x<lo or (hi is not None and x>hi):
  raise ValueError(f'{name}: nombre fini dans [{lo}, {hi}] attendu')

def validate(c):
 if c.get('schema_version')!=3 or c.get('mode') not in ('observation_only','research_only','paper_only'):
  raise ValueError('Configuration V3 requise. Aucun mode réel.')
 from datetime import datetime
 dates=[datetime.fromisoformat(c[k]) for k in ('data_start','start','end_exclusive')]
 if not dates[0]<=dates[1]<dates[2]: raise ValueError('Dates incoherentes')
 if not c['symbols'] or len(c['symbols'])>50 or len(set(c['symbols']))!=len(c['symbols']): raise ValueError('1 a 50 symboles uniques')
 if any(not re.fullmatch(r'[A-Z0-9]{2,25}',s) for s in c['symbols']): raise ValueError('Symbole invalide')
 if not c['timeframes'] or not set(c['timeframes'])<=TF_MS.keys(): raise ValueError('4h/1d uniquement')
 if c['signal']['opposite_policy'] not in ('hedge','net_flip'): raise ValueError('Politique inconnue')
 if c['signal']['trigger_source'] not in ('last','mark'): raise ValueError('Source de declenchement invalide')
 for k in ('breakout_pct','reintegration_pct','rearm_pct','max_entry_gap_pct'):
  finite(c['signal'][k],k,0,20)
 if c['signal']['max_breakouts_per_range']<1 or c['signal']['cooldown_ms']<1: raise ValueError('Rearmement/limite invalides')
 if c['signal']['breakout_mode'] not in ('fixed','volatility','range'): raise ValueError('Mode de seuil invalide')
 if set(c['agents']) != {'breakout','reintegration'}: raise ValueError('Deux stratégies explicites requises')
 for name,a in c['agents'].items():
  validate_agent(a,c['timeframes'])
  for tf,over in a.get('timeframe_overrides',{}).items():
   if tf not in TF_MS or not set(over)<=set(AGENT): raise ValueError('Override agent interdit/inconnu')
   validate_agent({**a,**over},[tf])
 for tf,over in c.get('signal_timeframe_overrides',{}).items():
  if tf not in TF_MS or not set(over)<=set(DEFAULT['signal']): raise ValueError('Override signal invalide')
  validate_signal({**c['signal'],**over})
 validate_signal(c['signal'])
 r=c['risk']; finite(r['initial_capital_usd'],'capital',1)
 if not 0<r['risk_per_trade_pct']<=r['max_open_risk_pct']<=2: raise ValueError('Risque global maximal de recherche: 2%')
 if not 1<=r['max_positions']<=20 or not 1<=r['leverage_limit']<=3: raise ValueError('Limites risque invalides')
 if r['pause_drawdown_pct'] is not None: finite(r['pause_drawdown_pct'],'drawdown',0.01,100)
 for k in ('max_gross_multiple','episode_loss_budget_pct','max_same_side_risk_pct'): finite(r[k],k,0.001)
 e=c['execution']
 for k in ('fee_pct','slippage_pct','spread_proxy_pct'): finite(e[k],k,0,5)
 for k in ('latency_ms','order_ttl_ms','max_quote_age_ms','max_trade_gap_ms','max_mark_age_ms'): finite(e[k],k,0)
 if e['order_ttl_ms']<=e['latency_ms']: raise ValueError('TTL doit depasser la latence')
 if not 0<e['participation']<=1: raise ValueError('Participation invalide')
 if e['stop_trigger_source'] not in ('last','mark'): raise ValueError('Source stop invalide')
 if e['funding_mode'] not in ('historical','none_unavailable','adverse_proxy'): raise ValueError('Financement invalide')
 for rule in [e['rules_default'],*e['rules'].values()]:
  for k in ('tick','qty_step','min_qty','min_notional'): finite(rule[k],k,1e-12)
 rr=c['range']
 if rr['method'] not in ('horizontal','donchian'): raise ValueError('Detecteur inconnu')
 if not 0<rr['touch_band_fraction']<0.5 or not 0<rr['min_width_pct']<rr['max_width_pct']<100: raise ValueError('Range invalide')
 for tf in c['timeframes']:
  if not 4<=rr['min_bars'][tf]<=rr['max_bars'][tf] or rr['max_bars'][tf]>2000: raise ValueError('Historique range invalide')
  if rr['expiry_bars'][tf]<1: raise ValueError('Expiration invalide')
 q=c['research']
 if not 0<q['initial_train_fraction']<q['development_fraction']<1: raise ValueError('Partitions invalides')
 if not 1<=q['folds']<=10 or q['max_variants']>100: raise ValueError('Recherche excessive')
 if c['universe']['kind'] not in ('static_exploratory','point_in_time'): raise ValueError('Univers inconnu')
 if c['universe']['kind']=='point_in_time' and not c['universe']['snapshots_file']: raise ValueError('Snapshots historiques requis, jamais inventes')


 # No unknown experiment/agent knobs and no dynamic risk overrides.
 unknown=set(c)-set(DEFAULT)-{'signal_timeframe_overrides'}
 if unknown: raise ValueError(f'Clés de configuration inconnues : {sorted(unknown)}')
 for tf in c['timeframes']:
  if not isinstance(rr['lookbacks'][tf],list) or any(not isinstance(w,int) or isinstance(w,bool) or w<4 or w>rr['max_bars'][tf] for w in rr['lookbacks'][tf]): raise ValueError('Fenêtres de range invalides')
 if not 1<=rr['bank_size']<=rr['max_candidates']<=128: raise ValueError('Banque bornée requise')
 for k in ('approach_bars','major_pivot_left','major_pivot_right'):
  if not isinstance(rr[k],int) or isinstance(rr[k],bool) or rr[k]<1: raise ValueError('Paramètre entier de structure requis')
 finite(rr['major_min_atr'],'pivot ATR',0.01)
 o=c['observation']
 if o['require_verified_archives'] is not True or o['register_viewed_periods'] is not True:
  raise ValueError('Provenance et registre obligatoires en V3')
 finite(o['max_event_silence_ms'],'silence',1)
 if not isinstance(o['allow_partial_coverage'],bool) or not isinstance(o['export_event_catalog'],bool): raise ValueError('Options observation booléennes requises')
 hs=o['horizons_seconds']
 if not isinstance(hs,list) or not hs or len(set(hs))!=len(hs) or any(isinstance(h,bool) or not isinstance(h,int) or not 1<=h<=86400 for h in hs): raise ValueError('Horizons observés uniques de 1 à 86400 secondes')
 al=c['allocation']
 if not isinstance(al['correlation_enabled'],bool):raise ValueError('Activation de corrélation booléenne')
 if al['mode'] not in ('sequential','precommitted','economic_available'): raise ValueError('Allocation inconnue')
 valid_ids={f'{a}:{tf}' for a in ('breakout','reintegration') for tf in TF_MS}
 if set(al['agent_priority'])!=valid_ids or len(al['agent_priority'])!=4: raise ValueError('Priorités fixes incomplètes/dupliquées')
 if al['correlation_tf'] not in TF_MS or not 3<=al['correlation_min_pairs']<=al['correlation_lookback']<=1000: raise ValueError('Fenêtre de corrélation invalide')
 finite(al['correlation_threshold'],'corrélation',0,1)
 finite(al['max_correlated_risk_pct'],'risque corrélé',0.001,r['max_open_risk_pct'])
 if al['missing_correlation_policy'] not in ('diagnostic_only','abstain'): raise ValueError('Données corrélation inconnues')
 le=c['learning']
 if not isinstance(le['enabled'],bool):raise ValueError('Activation apprentissage booléenne')
 if le['objective'] not in ('ridge_net_r','decomposed_net_r') or le['unknown_policy'] not in ('abstain','approved_reference'): raise ValueError('Apprentissage invalide')
 if le['unknown_policy']=='approved_reference' and le['reference_fallback_approved'] is not True: raise ValueError('Repli non approuvé')
 for k in ('min_rows','min_calibration_rows','min_validation_rows','min_distinct_families'):
  if not isinstance(le[k],int) or isinstance(le[k],bool) or le[k]<2: raise ValueError('Effectif minimal invalide')
 for k in ('max_disagreement_r','max_model_age_days'): finite(le[k],k,0.000001)
 finite(le['min_expected_net_r'],'valeur nette',0)
 finite(le['ood_quantile'],'quantile',0.5,1)
 finite(le['max_calibration_error'],'calibration',0.001,1)
 if c['mode']=='observation_only' and le['enabled']: raise ValueError('Pas de modèle actif en observation seule')
 if not isinstance(q['require_one_factor_at_a_time'],bool):raise ValueError('Recherche à un facteur booléenne requise')
 finite(q['calendar_max_state_age_ms'],'ancienneté état de compte',1)
 if q['selection_metric'] not in ('calendar_net_return',): raise ValueError('Le taux de réussite ou R moyen seuls ne sont pas un objectif de compte')
 if q['global_registry_required'] is not True: raise ValueError('Registre global obligatoire')
 for k in ('max_positions','leverage_limit'):
  if isinstance(r[k],bool): raise ValueError('Booléen interdit pour limite numérique')
 # Validate finite nested numeric values as well as base values.
 def walk(obj):
  if isinstance(obj,dict):
   for v in obj.values(): walk(v)
  elif isinstance(obj,list):
   for v in obj: walk(v)
  elif isinstance(obj,float) and not math.isfinite(obj): raise ValueError('NaN/Inf interdit')
 walk(c)


def validate_signal(s):
 if s['reintegration_window'] not in ('same_candle','elapsed'): raise ValueError('Fenêtre de réintégration inconnue')
 if not isinstance(s['same_structure_candle'],bool): raise ValueError('Booléen explicite requis')
 if (s['reintegration_window']=='same_candle') != s['same_structure_candle']:
  raise ValueError('Fenêtre et same_structure_candle doivent être cohérents')
 finite(s['max_reintegration_ms'],'fenêtre écoulée',1)
 for k in ('breakout_pct','reintegration_pct','rearm_pct','max_entry_gap_pct'):
  finite(s[k],k,0,20)
 if s['trigger_source'] not in ('last','mark'): raise ValueError('Source de déclenchement invalide')
 if s['breakout_mode'] not in ('fixed','volatility','range'): raise ValueError('Mode de cassure inconnu')
 if s['opposite_policy'] not in ('hedge','net_flip'): raise ValueError('Mode positions inconnu')
 if not isinstance(s['max_breakouts_per_range'],int) or isinstance(s['max_breakouts_per_range'],bool) or s['max_breakouts_per_range']<1: raise ValueError('Tentatives entières requises')
 finite(s['cooldown_ms'],'temporisation',1)
 for k in ('breakout_vol_multiplier','breakout_range_fraction','breakout_min_pct','breakout_max_pct'): finite(s[k],k,0.000001)
 if s['breakout_min_pct']>s['breakout_max_pct']: raise ValueError('Bornes de cassure incohérentes')


def validate_agent(a,timeframes):
 if not set(a)<=set(AGENT)|{'timeframe_overrides'}: raise ValueError('Clé agent inconnue / risque non modifiable par agent')
 if not isinstance(a['enabled'],bool): raise ValueError('Agent enabled doit être booléen')
 for k in ('stop_pct','runner_trail_pct','stop_min_pct','stop_max_pct'):
  finite(a[k],k,0.000001,50)
 for k in ('tp1_fraction','tp2_fraction','runner_fraction'): finite(a[k],k,0,1)
 if not math.isclose(a['tp1_fraction']+a['tp2_fraction']+a['runner_fraction'],1,rel_tol=0,abs_tol=1e-10):
  raise ValueError('Fractions TP1 + TP2 + runner doivent totaliser 1')
 targets=[]
 for n in (1,2):
  if a[f'tp{n}_fraction']>0:
   finite(a[f'tp{n}_pct'],f'TP{n}',0.000001,1000); targets.append(a[f'tp{n}_pct'])
 if len(targets)==2 and targets[0]>=targets[1]: raise ValueError('Objectifs actifs non croissants')
 if a['breakeven_trigger_pct'] is not None: finite(a['breakeven_trigger_pct'],'BE',0,50)
 if a['stop_mode'] not in ('fixed','volatility','range','boundary','excursion'): raise ValueError('Stop inconnu')
 if a['stop_min_pct']>a['stop_max_pct']: raise ValueError('Bornes de stop invalides')
 for k in ('stop_boundary_margin_pct','stop_excursion_margin_pct'): finite(a[k],k,0,20)
 if a['trailing_activation'] not in ('after_last_target','price_pct','initial_r','immediate','disabled'): raise ValueError('Activation trailing inconnue')
 if a['runner_fraction']>0:
  if a['trailing_activation']=='disabled': raise ValueError('Runner sans gestion suiveuse')
  if not targets and a['trailing_activation']=='after_last_target': raise ValueError('Aucun TP : choisir une activation trailing indépendante')
 for k in ('trailing_trigger_pct','trailing_trigger_r'): finite(a[k],k,0,1000)
 for tf in timeframes: finite(a['max_holding_hours'][tf],'détention',0.01,720)
 if a['model_path'] is not None and not isinstance(a['model_path'],str): raise ValueError('Chemin modèle invalide')

def agent_config(c,name,tf):
 a=deepcopy(c['agents'][name]); a.update(a.pop('timeframe_overrides',{}).get(tf,{})); return a

def threshold_pct(mode,fixed,volatility_pct,width_pct,vol_multiplier,range_fraction,minimum,maximum):
 v=fixed if mode=='fixed' else volatility_pct*vol_multiplier if mode=='volatility' else width_pct*range_fraction
 return min(maximum,max(minimum,v)) if mode!='fixed' else v
