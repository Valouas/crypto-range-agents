"""Public read-only archives, checksums, event streams and explicit provenance."""
from __future__ import annotations
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import csv, gzip, hashlib, heapq, io, json, os, time, zipfile, itertools
import pandas as pd
import requests
from .types import Event
from .config import TF_MS, digest
from .policy import require_capability
from .ranges import validate_structure, build_schedule

BASE='https://data.binance.vision/data/futures/um'

def utc_ms(s): return int(pd.Timestamp(s,tz='UTC').timestamp()*1000) if pd.Timestamp(s).tz is None else int(pd.Timestamp(s).timestamp()*1000)

def sha256_file(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()

def safe_path(root,relative):
 root=Path(root).resolve(); p=(root/relative).resolve()
 if not p.is_relative_to(root): raise ValueError('Manifest path escapes dataset')
 return p

def atomic_json(p,value):
 p=Path(p); p.parent.mkdir(parents=True,exist_ok=True); tmp=p.with_suffix(p.suffix+'.tmp')
 tmp.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8'); os.replace(tmp,p)

def fetch_checked(url,path,session=None):
 if not url.startswith(BASE+'/'): raise ValueError('Only approved public archive host/path')
 path=Path(path); path.parent.mkdir(parents=True,exist_ok=True); s=session or requests.Session()
 # Never trust a cache file without the vendor checksum.
 response=s.get(url+'.CHECKSUM',timeout=(10,40)); response.raise_for_status()
 expected=response.text.split()[0].lower()
 if len(expected)!=64 or any(c not in '0123456789abcdef' for c in expected): raise ValueError('Invalid vendor SHA256')
 if path.exists() and sha256_file(path)==expected: return {'url':url,'sha256':expected,'verified':True}
 tmp=path.with_suffix('.part')
 try:
  with s.get(url,stream=True,timeout=(10,90)) as r:
   r.raise_for_status()
   with open(tmp,'wb') as f:
    for chunk in r.iter_content(1024*1024):
     if chunk: f.write(chunk)
  if sha256_file(tmp)!=expected: raise ValueError('Checksum mismatch')
  os.replace(tmp,path)
 finally:
  if tmp.exists(): tmp.unlink()
 return {'url':url,'sha256':expected,'verified':True}

def csv_rows(zpath):
 with zipfile.ZipFile(zpath) as z:
  names=[n for n in z.namelist() if n.endswith('.csv')]
  if len(names)!=1: raise ValueError('One CSV expected in archive')
  if z.getinfo(names[0]).file_size>50_000_000_000: raise ValueError('Archive unreasonably large')
  with z.open(names[0]) as raw:
   for row in csv.reader(io.TextIOWrapper(raw,encoding='utf-8-sig')):
    if row and row[0].strip().isdigit(): yield row

def read_bars_archive(path,tf):
 rows=[]
 for r in csv_rows(path):
  ts=int(r[0]); ts=ts//1000 if ts>10**14 else ts
  rows.append([ts,*map(float,r[1:5])])
 df=pd.DataFrame(rows,columns=['timestamp_ms','open','high','low','close'])
 return validate_structure(df,tf)

def read_trade_archive(path,symbol,kind='aggTrades'):
 previous_id=None; previous_ts=-1
 for r in csv_rows(path):
  seq=int(r[0]); ts=int(r[5] if kind=='aggTrades' else r[4]); ts=ts//1000 if ts>10**14 else ts
  if previous_id is not None and seq<=previous_id: raise ValueError('Non-monotonic transaction IDs')
  if ts<previous_ts: raise ValueError('Non-monotonic exchange timestamps')
  # IDs need not be contiguous across venues/format revisions; gaps are reported by audit, not fabricated.
  e=Event(ts,symbol,'trade',float(r[1]),float(r[2]),seq,source='binance_public_'+kind)
  e.validate(); previous_id=seq; previous_ts=ts; yield e

def write_events(path,events):
 path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
 count=0; first=None; last=None
 with gzip.open(path,'wt',encoding='utf-8') as f:
  for e in events:
   e.validate(); f.write(json.dumps(asdict(e),separators=(',',':'))+'\n'); count+=1
   first=e.ts if first is None else first; last=e.ts
 return {'path':str(path),'rows':count,'first_ms':first,'last_ms':last,'sha256':sha256_file(path)}

def read_events(path,start_ms=0,end_ms=10**18):
 opener=gzip.open if str(path).endswith('.gz') else open
 previous=None
 with opener(path,'rt',encoding='utf-8') as f:
  for line in f:
   if not line.strip(): continue
   e=Event(**json.loads(line)); e.validate()
   if previous and e.key()<previous: raise ValueError(f'Events not sorted: {path}')
   previous=e.key()
   if e.ts>=end_ms: break
   if e.ts>=start_ms: yield e

def merged_events(files,start_ms=0,end_ms=10**18):
 return heapq.merge(*(read_events(p,start_ms,end_ms) for p in files),key=lambda e:e.key())

def collect_structure(cfg,root):
 require_capability('public_collection')
 root=Path(root); a,b=utc_ms(cfg['data_start']),utc_ms(cfg['end_exclusive']); tables=[]; archives=[]
 session=requests.Session()
 for symbol in cfg['symbols']:
  for tf in cfg['timeframes']:
   parts=[]
   for month in pd.period_range(pd.Timestamp(cfg['data_start']).to_period('M'),(pd.Timestamp(cfg['end_exclusive'])-pd.Timedelta(milliseconds=1)).to_period('M'),freq='M'):
    name=f'{symbol}-{tf}-{month}.zip'; url=f'{BASE}/monthly/klines/{symbol}/{tf}/{name}'
    path=root/'archives'/name; archives.append(fetch_checked(url,path,session)); parts.append(read_bars_archive(path,tf))
   df=pd.concat(parts,ignore_index=True); df=df.loc[(df.timestamp_ms>=a)&(df.timestamp_ms<b)]
   df=validate_structure(df,tf)
   if df.empty: raise ValueError(f'No structural bars: {symbol}/{tf}')
   # Do not silently treat listing periods or missing bars as flat prices.
   gaps=int((df.timestamp_ms.diff().dropna()!=TF_MS[tf]).sum())
   p=root/'structures'/f'{symbol}-{tf}.csv.gz'; p.parent.mkdir(parents=True,exist_ok=True); df.to_csv(p,index=False,compression='gzip')
   tables.append({'symbol':symbol,'tf':tf,'path':str(p.relative_to(root)),'rows':len(df),'gaps':gaps,'sha256':sha256_file(p)})
   print(f'{symbol} {tf}: {len(df)} closed bars, {gaps} gaps',flush=True)
 manifest_path=root/'manifest.json'
 m=json.loads(manifest_path.read_text()) if manifest_path.exists() else {'schema_version':2,'synthetic':False,'events':[]}
 m.update(source='Binance public USD-M futures archives',structures=tables,structure_archives=archives,
          data_start=cfg['data_start'],start=cfg['start'],end_exclusive=cfg['end_exclusive'])
 atomic_json(manifest_path,m); return m

def collect_trades(cfg,root,kind='aggTrades',start=None,end=None):
 require_capability('public_collection')
 root=Path(root); mp=root/'manifest.json'
 if not mp.exists(): raise ValueError('Collect structural data first')
 m=json.loads(mp.read_text()); a=utc_ms(start or cfg['start']); b=utc_ms(end or cfg['end_exclusive'])
 if a>=b: raise ValueError('Empty date interval')
 session=requests.Session(); records=[]
 for sym in cfg['symbols']:
  for day in pd.date_range(pd.Timestamp(a,unit='ms',tz='UTC').floor('D'),pd.Timestamp(b-1,unit='ms',tz='UTC').floor('D'),freq='D'):
   daystr=day.strftime('%Y-%m-%d'); name=f'{sym}-{kind}-{daystr}.zip'
   url=f'{BASE}/daily/{kind}/{sym}/{name}'; archive=root/'archives'/name
   proof=fetch_checked(url,archive,session)
   path=root/'events'/f'{sym}-{kind}-{daystr}.jsonl.gz'
   info=write_events(path,(e for e in read_trade_archive(archive,sym,kind) if a<=e.ts<b))
   info.update(path=str(path.relative_to(root)),symbol=sym,kind=kind,archive_proof=proof,
               requested_start_ms=max(a,int(day.timestamp()*1000)),requested_end_ms=min(b,int(day.timestamp()*1000)+86400000))
   records.append(info); print(f'{sym} {daystr}: {info["rows"]:,} events',flush=True)
 # No silent overwrite or double-count of overlapping transaction streams.
 old=[r for r in m.get('events',[]) if r['path'] not in {v['path'] for v in records}]
 if any(r.get('kind') in ('trades','aggTrades') and r.get('kind')!=kind for r in old): raise ValueError('Do not mix trades and aggregate copies in same dataset')
 m['events']=old+records; m['event_precision']=kind+' (not full order book)'; atomic_json(mp,m); return m

def collect_funding(cfg,root):
 require_capability('public_collection')
 root=Path(root); mp=root/'manifest.json'; m=json.loads(mp.read_text()); records=[]
 for sym in cfg['symbols']:
  a,b=utc_ms(cfg['start']),utc_ms(cfg['end_exclusive']); rows=[]
  while a<b:
   r=requests.get('https://fapi.binance.com/fapi/v1/fundingRate',params={'symbol':sym,'startTime':a,'endTime':b-1,'limit':1000},timeout=(10,40)); r.raise_for_status()
   body=r.json()
   if not isinstance(body,list): raise ValueError('Funding API response unexpected')
   if not body: break
   for x in body:
    ts=int(x['fundingTime']); price=float(x.get('markPrice',0))
    if price<=0: raise ValueError('Funding settlement mark price missing')
    if a<=ts<b: rows.append(Event(ts,sym,'funding',price,rate=float(x['fundingRate']),seq=ts,source='binance_funding_rest'))
   nxt=max(int(x['fundingTime']) for x in body)+1
   if nxt<=a: raise ValueError('Funding pagination stalled')
   a=nxt; time.sleep(0.7)
  if not rows: raise ValueError(f'Funding absent: {sym}')
  p=root/'events'/f'{sym}-funding.jsonl.gz'; info=write_events(p,sorted(rows,key=lambda e:e.key()))
  info.update(path=str(p.relative_to(root)),symbol=sym,kind='funding',source='https://fapi.binance.com/fapi/v1/fundingRate')
  records.append(info)
 m['events']=[r for r in m.get('events',[]) if r.get('kind')!='funding']+records
 m['funding_history_collected']=True; atomic_json(mp,m); return m

class Dataset:
 def __init__(self,root,cfg,verify=True):
  self.root=Path(root); self.cfg=cfg
  self.manifest=json.loads((self.root/'manifest.json').read_text(encoding='utf-8'))
  if self.manifest.get('synthetic'): require_capability('synthetic_market')
  if self.manifest.get('schema_version')!=2: raise ValueError('Dataset V2 required')
  # Content-centric identity: moving the dataset or reordering the manifest is not a new holdout.
  proofs=[(kind,r.get('symbol'),r.get('tf',r.get('kind')),r['sha256']) for kind in ('structures','events') for r in self.manifest.get(kind,[])]
  self.fingerprint=digest(sorted(proofs,key=str))
  if self.manifest.get('synthetic') is False:
   if verify is not True:raise ValueError('La provenance réelle ne peut pas être désactivée')
   from copy import deepcopy
   from .observation import RealDataset
   observation_cfg=deepcopy(cfg);observation_cfg['mode']='observation_only';observation_cfg['learning']['enabled']=False
   authentic=RealDataset(root,observation_cfg)
   self.fingerprint=authentic.fingerprint
  elif self.manifest.get('synthetic') is not True:
   raise ValueError('Provenance réelle ou fixture explicitement autorisée requise')
  self.structures={}; self.files=[]; self.event_records=[]; self.schedules={}; self.event_partitions={}
  for item in self.manifest.get('structures',[]):
   p=safe_path(root,item['path'])
   if verify and sha256_file(p)!=item['sha256']: raise ValueError('Modified structural file')
   key=(item['symbol'],item['tf'])
   if key[0] in cfg['symbols'] and key[1] in cfg['timeframes']:
    self.structures[key]=validate_structure(pd.read_csv(p),key[1])
  for item in self.manifest.get('events',[]):
   p=safe_path(root,item['path'])
   if verify and sha256_file(p)!=item['sha256']: raise ValueError('Modified event file')
   if item.get('symbol') in cfg['symbols'] or item.get('symbol')=='MULTI':
    self.files.append(p); self.event_records.append({**item,'absolute_path':p})
  missing={(s,t) for s in cfg['symbols'] for t in cfg['timeframes']}-self.structures.keys()
  if missing: raise ValueError(f'Missing structure: {sorted(missing)}')
  if cfg['execution']['funding_mode']=='historical':
   funded={r.get('symbol') for r in self.event_records if r.get('kind')=='funding'}
   if set(cfg['symbols'])-funded: raise ValueError('Historical funding requested but missing for some symbols')
 def schedule(self,range_cfg=None):
  cfg=range_cfg or self.cfg['range']
  key=digest(cfg)
  if key not in self.schedules:
   self.schedules[key]={k:build_schedule(b,*k,cfg) for k,b in self.structures.items()}
  return self.schedules[key]
 def events(self,a=None,b=None):
  if not self.files: raise ValueError('No transaction events. Collect trades/aggTrades, no silent OHLC substitution.')
  a=utc_ms(self.cfg['start']) if a is None else a
  b=utc_ms(self.cfg['end_exclusive']) if b is None else b
  channels={}
  for r in self.event_records:
   if r.get('first_ms') is not None and (r['first_ms']>=b or r.get('last_ms',a)<a): continue
   channels.setdefault((r.get('symbol'),r.get('kind')),[]).append(r)
  streams=[]
  for records in channels.values():
   ordered=sorted(records,key=lambda r:r.get('first_ms') or r.get('requested_start_ms',0))
   previous_end=None
   for r in ordered:
    if previous_end is not None and r.get('first_ms',previous_end+1)<=previous_end:
     raise ValueError('Overlapping event files within one channel; do not double-count observations')
    previous_end=r.get('last_ms',previous_end)
   # At most one daily file open per symbol/channel, not thousands of file descriptors.
   streams.append(itertools.chain.from_iterable(read_events(r['absolute_path'],a,b) for r in ordered))
  key=(a,b)
  if key in self.event_partitions: return iter(self.event_partitions[key])
  merged=heapq.merge(*streams,key=lambda e:e.key())
  if sum(r.get('rows',200001) for r in self.event_records)<=200000:
   # Cache only requested partitions, not the held-out future. Large histories remain streaming.
   self.event_partitions[key]=list(merged);return iter(self.event_partitions[key])
  return merged
 def coverage(self,a,b):
  rows=[]
  for sym in self.cfg['symbols']:
   intervals=sorted((max(a,int(x.get('requested_start_ms',x.get('first_ms') or a))),min(b,int(x.get('requested_end_ms',(x.get('last_ms') or a)+1)))) for x in self.manifest.get('events',[]) if x.get('symbol') in (sym,'MULTI') and x.get('kind') not in ('funding','mark','quote'))
   frontier=a; gaps=[]
   for lo,hi in intervals:
    if hi<=lo: continue
    if lo>frontier: gaps.append([frontier,lo])
    frontier=max(frontier,hi)
   if frontier<b: gaps.append([frontier,b])
   rows.append({'symbol':sym,'missing_intervals':gaps})
  return rows
