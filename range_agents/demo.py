"""Reproducible artificial prices, never market performance."""
from copy import deepcopy
from pathlib import Path
import math
import numpy as np
import pandas as pd
from .config import load_config,TF_MS
from .types import Event
from .data import atomic_json,write_events,sha256_file,utc_ms

def generate(root,days=160,symbol_count=2):
 from .policy import require_capability
 require_capability('synthetic_market')
 if not 40<=days<=730: raise ValueError('Demo: 40 to 730 artificial days')
 root=Path(root); root.mkdir(parents=True,exist_ok=True)
 cfg=load_config(); cfg['symbols']=['BTCUSDT','ETHUSDT'][:symbol_count]
 a=utc_ms('2024-01-01'); warm=min(40,days//3)
 cfg.update(data_start='2024-01-01',start=pd.Timestamp(a+warm*86400000,unit='ms').strftime('%Y-%m-%d'),end_exclusive=pd.Timestamp(a+days*86400000,unit='ms').strftime('%Y-%m-%d'))
 cfg['execution'].update(max_trade_gap_ms=7_200_000,latency_ms=100,participation=.1)
 cfg['research']['purpose']='smoke_descriptive'
 records=[]; tables=[]
 for j,symbol in enumerate(cfg['symbols']):
  hours=np.arange(days*24); cycle=hours//(40*24); phase=hours%(40*24)
  base=100+cycle*6+j*50
  price=base+5*np.sin(2*np.pi*phase/(10*24)+j*.15)
  # Alternating real/fake expansion trajectories are deliberately manufactured.
  for i,h in enumerate(phase):
   d=h/24
   if 30<=d<32:
    price[i]=base[i]+5+(d-30)*3 if cycle[i]%2==0 else base[i]+5.3-(d-30)*4
   elif 32<=d<35: price[i]=base[i]+11-(d-32)*2
  minute_like=pd.DataFrame({'timestamp_ms':a+hours*3600000,'open':price,'high':price+.015,'low':price-.015,'close':price})
  for tf,dur in TF_MS.items():
   b=minute_like.copy(); b['bucket']=b.timestamp_ms//dur*dur
   b=b.groupby('bucket',sort=True).agg(open=('open','first'),high=('high','max'),low=('low','min'),close=('close','last')).reset_index().rename(columns={'bucket':'timestamp_ms'})
   p=root/'structures'/f'{symbol}-{tf}.csv.gz'; p.parent.mkdir(parents=True,exist_ok=True); b.to_csv(p,index=False,compression='gzip')
   tables.append({'symbol':symbol,'tf':tf,'rows':len(b),'path':str(p.relative_to(root)),'sha256':sha256_file(p),'gaps':0})
  def stream():
   seq=0
   for h,p in zip(hours,price):
    ts=a+int(h)*3600000
    for dt,delta in [(0,0.),(150,.005),(350,-.005),(600,0.)]:
     seq+=1
     yield Event(ts+dt,symbol,'trade',float(p+delta),qty=1000.,seq=seq,source='SYNTHETIC_HOURLY_WITH_MICRO_BURSTS')
  p=root/'events'/f'{symbol}-synthetic.jsonl.gz'; info=write_events(p,stream())
  info.update(path=str(p.relative_to(root)),symbol=symbol,kind='synthetic',requested_start_ms=a,requested_end_ms=a+days*86400000)
  records.append(info)
 manifest={'schema_version':2,'synthetic':True,'source':'MANUFACTURED_PRICES_NOT_MARKET_DATA',
  'structures':tables,'events':records,'data_start':cfg['data_start'],'start':cfg['start'],'end_exclusive':cfg['end_exclusive'],
  'event_precision':'Manufactured hourly states with 4 artificial intrasecond observations; no market claim'}
 atomic_json(root/'manifest.json',manifest); atomic_json(root/'config.json',cfg)
 return cfg
