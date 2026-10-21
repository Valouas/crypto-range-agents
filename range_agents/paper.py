"""Public, read-only paper adapter. No keys, account endpoints, signed requests or orders.
Transport is optional and not an assurance of production venue behavior.
"""
from __future__ import annotations
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import json, queue, threading, time
import pandas as pd
import requests
from .config import TF_MS
from .types import Event
from .ranges import build_schedule,validate_structure
from .engine import Simulator
from .storage import StateStore
from .data import atomic_json
from .report import export_result

REST='https://fapi.binance.com'

def endpoints(symbols):
 market=[]; public=[]
 for s in symbols:
  s=s.lower(); market.extend([s+'@aggTrade',s+'@markPrice@1s',s+'@kline_4h',s+'@kline_1d']);public.append(s+'@bookTicker')
 return {'market':'wss://fstream.binance.com/market/stream?streams='+'/'.join(market),
         'public':'wss://fstream.binance.com/public/stream?streams='+'/'.join(public)}

def decode_message(message,received_ms,max_age_ms=5000):
 d=json.loads(message) if isinstance(message,str) else message; d=d.get('data',d)
 if 's' not in d or d.get('st',1)!=1: return None
 exchange_ms=int(d.get('E',d.get('T',received_ms)))
 if received_ms-exchange_ms>max_age_ms or exchange_ms-received_ms>max_age_ms: raise ValueError('Stale message or local clock out of sync')
 kind=d.get('e'); s=d['s']; kwargs={'received_ms':received_ms,'source':'PUBLIC_WEBSOCKET_RECEPTION_TIME'}
 if kind=='aggTrade':
  return Event(received_ms,s,'trade',float(d['p']),float(d['q']),int(d['a']),**kwargs)
 if kind=='bookTicker':
  return Event(received_ms,s,'quote',seq=int(d['u']),bid=float(d['b']),ask=float(d['a']),bid_qty=float(d['B']),ask_qty=float(d['A']),**kwargs)
 if kind=='markPriceUpdate': return Event(received_ms,s,'mark',float(d['p']),seq=exchange_ms,**kwargs)
 if kind=='kline' and d.get('k',{}).get('x'):
  k=d['k']; return {'symbol':s,'tf':k['i'],'closed_bar':[int(k['t']),*map(float,[k['o'],k['h'],k['l'],k['c']])],
                    'received_ms':received_ms,'exchange_ms':exchange_ms}
 return None

def bootstrap(cfg,now):
 bars={}
 for s in cfg['symbols']:
  for tf in cfg['timeframes']:
   limit=min(1500,cfg['range']['max_bars'][tf]+30)
   r=requests.get(REST+'/fapi/v1/klines',params={'symbol':s,'interval':tf,'limit':limit,'endTime':now},timeout=(10,40));r.raise_for_status()
   body=r.json()
   if not isinstance(body,list): raise ValueError('Unexpected public kline response')
   rows=[[int(x[0]),*map(float,x[1:5])] for x in body if int(x[0])+TF_MS[tf]<=now]
   frame=validate_structure(pd.DataFrame(rows,columns=['timestamp_ms','open','high','low','close']),tf)
   if len(frame)<cfg['range']['min_bars'][tf]: raise ValueError('Not enough public closed bars to initialize')
   bars[(s,tf)]=frame
 return bars

def run_paper(cfg,out,seconds=300):
 from .policy import require_capability
 require_capability('paper')
 import websocket
 if not 1<=seconds<=86400: raise ValueError('Paper session duration must be 1..86400 seconds')
 if len(cfg['symbols'])>3: raise ValueError('This experimental durable paper adapter is capped at 3 symbols; scale testing required')
 c=deepcopy(cfg);c['mode']='paper_only';c['execution']['require_quotes']=True
 if c['execution']['funding_mode']=='historical': raise ValueError('Paper funding settlement collector not wired: choose explicit none_unavailable/proxy')
 out=Path(out);out.mkdir(parents=True,exist_ok=True);now=int(time.time()*1000)
 bars=bootstrap(c,now);schedule={k:build_schedule(b,*k,c['range']) for k,b in bars.items()}
 sim=Simulator(c,schedule,now,10**18,'public-paper');store=StateStore(out/'paper_state.sqlite')
 restored=store.load(c)
 if restored:
  sim=restored
  # Closed bars fetched now may extend the stored schedule but not rewrite known decisions.
  for k,rr in schedule.items():
   ids={r.id for r in sim.schedules.get(k,[])}
   sim.schedules.setdefault(k,[]).extend(r for r in rr if r.id not in ids and r.known_ms>sim.now)
   sim.schedules[k].sort(key=lambda r:r.known_ms)
 q=queue.Queue(maxsize=10000);stop=threading.Event();apps=[]
 def worker(url):
  while not stop.is_set():
   def enqueue(ws,msg):
    try:q.put(('message',int(time.time()*1000),msg),timeout=1)
    except queue.Full:stop.set()
   def error(ws,err):
    try:q.put_nowait(('error',int(time.time()*1000),str(err)))
    except queue.Full:stop.set()
   app=websocket.WebSocketApp(url,on_message=enqueue,on_error=error);apps.append(app)
   app.run_forever(ping_interval=20,ping_timeout=10)
   stop.wait(2)
 threads=[threading.Thread(target=worker,args=(u,),daemon=True) for u in endpoints(c['symbols']).values()]
 for t in threads:t.start()
 deadline=time.monotonic()+seconds;count=0
 try:
  with open(out/'received_events.jsonl','a',encoding='utf-8') as log:
   while time.monotonic()<deadline and not stop.is_set():
    try:typ,received,raw=q.get(timeout=1)
    except queue.Empty:
     ts=max(int(time.time()*1000),sim.now+1);store.process(sim,Event(ts,'ALL','heartbeat',seq=ts,source='PAPER_HEARTBEAT'));continue
    received=max(received,sim.now+1)
    if typ=='error':sim._incident('public_transport_error',message=raw);continue
    try:item=decode_message(raw,received)
    except (ValueError,KeyError,TypeError) as exc:sim._incident('public_message_rejected',message=str(exc));continue
    if isinstance(item,Event):
     store.process(sim,item);log.write(json.dumps(asdict(item))+'\n');log.flush();count+=1
    elif isinstance(item,dict):
     key=(item['symbol'],item['tf'])
     if key not in bars:continue
     b=pd.concat([bars[key],pd.DataFrame([item['closed_bar']],columns=bars[key].columns)]).drop_duplicates('timestamp_ms').sort_values('timestamp_ms')
     b=b.tail(c['range']['max_bars'][key[1]]+30).reset_index(drop=True);bars[key]=b
     rr=build_schedule(b,*key,c['range']);ids={r.id for r in sim.schedules[key]}
     # Only activate the newly closed bar after it has actually been received.
     from dataclasses import replace
     for r in rr:
      if r.id not in ids and r.known_ms>=item['closed_bar'][0]+TF_MS[key[1]]:
       sim.schedules[key].append(replace(r,known_ms=max(r.known_ms,received)))
     sim.schedules[key].sort(key=lambda r:r.known_ms)
    if count and count%1000==0:print(f'Paper: {count} events, {len(sim.positions)} fictional positions',flush=True)
 except KeyboardInterrupt:pass
 finally:
  stop.set()
  for app in apps:app.close()
  for t in threads:t.join(timeout=3)
  store.close()
 manifest={'synthetic':False,'source':'Public WebSocket reception-time paper simulation','funding':'unavailable or explicit adverse proxy','no_real_orders':True}
 export_result(sim.result(),out,c,manifest)
 atomic_json(out/'session.json',{'events':count,'no_real_orders':True,'scope':'EXPERIMENTAL_PAPER_MAX3_SYMBOLS','stopped_with_open_positions':len(sim.positions)})
 return sim.result()
