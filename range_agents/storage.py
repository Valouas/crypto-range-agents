"""SQLite WAL event journal, JSON snapshots, idempotent simulated order outbox.
There is no pickle loading and no exchange credential anywhere in these objects.
"""
from __future__ import annotations
from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import json, sqlite3
from .config import digest
from .engine import Simulator
from .types import Event,Order,Position,Episode,RangeDef

SCALARS=['initial','cash','now','event_no','run_id','start_ms','end_ms','halted','peak','max_dd',
 'last_uid','last_payload','last_equity_log_ms','correlation_index','correlation_snapshot']
LISTS=['trades','signals','order_log','lifecycle','equity_log','funding_log','incidents','flip_queue']
MAPS=['prices','last_trade_ms','marks','family_attempts','family_loss','family_ids','range_rows','stats']

def snapshot(sim):
 state={'format':3,'config_hash':digest(sim.cfg),'scalars':{k:getattr(sim,k) for k in SCALARS},
 'lists':{k:getattr(sim,k) for k in LISTS},'maps':{k:dict(getattr(sim,k)) for k in MAPS},
 'positions':[asdict(p) for p in sim.positions.values()],'orders':[asdict(o) for o in sim.orders.values()],
 'episodes':[[list(key),asdict(ep)] for key,ep in sim.episodes.items()],
 'latest_ranges':[[list(key),r.row()] for key,r in sim.latest_ranges.items()],
 'schedules':[[list(key),[r.row() for r in rows]] for key,rows in sim.schedules.items()],
 'schedule_index':[[list(key),v] for key,v in sim.schedule_index.items()],
 'family_registry':[[r.row(),fid] for r,fid in sim.family_registry.items],
 'source_seq':[[list(key),v] for key,v in sim.previous_source_seq.items()],
 'quotes':{k:asdict(v) for k,v in sim.quotes.items()},
 'quote_used':[[list(key),v] for key,v in sim.quote_used.items()],
 'excluded_families':sorted(sim.excluded_families),'correlation_schedule':sim.correlation_schedule}
 return deepcopy(state)

def restore(cfg,state):
 if state['format']!=3 or state['config_hash']!=digest(cfg): raise ValueError('Snapshot/config version mismatch')
 s=Simulator(cfg,correlation_schedule=state.get('correlation_schedule',[]))
 for k,v in state['scalars'].items(): setattr(s,k,v)
 for k,v in state['lists'].items(): setattr(s,k,v)
 for k,v in state['maps'].items(): setattr(s,k,defaultdict(float,v) if k in ('family_loss',) else defaultdict(int,v) if k in ('stats','family_attempts') else v)
 s.positions={p['id']:Position(**p) for p in state['positions']}
 s.orders={o['id']:Order(**o) for o in state['orders']}
 s.episodes={tuple(k):Episode(**{**v,'range':RangeDef(**v['range'])}) for k,v in state['episodes']}
 s.latest_ranges={tuple(k):RangeDef(**v) for k,v in state['latest_ranges']}
 s.schedules={tuple(k):[RangeDef(**r) for r in v] for k,v in state['schedules']}
 s.schedule_index=defaultdict(int,{tuple(k):v for k,v in state['schedule_index']})
 s.family_registry.items=[(RangeDef(**r),fid) for r,fid in state['family_registry']]
 s.previous_source_seq={tuple(k):v for k,v in state['source_seq']}
 s.quotes={k:Event(**v) for k,v in state['quotes'].items()}
 s.quote_used={tuple(k):v for k,v in state['quote_used']}
 s.excluded_families=set(state['excluded_families'])
 s.signal_index={v['id']:v for v in s.signals}
 s.check_invariants(); return s

class StateStore:
 def __init__(self,path):
  path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
  self.db=sqlite3.connect(path); self.db.execute('PRAGMA journal_mode=WAL'); self.db.execute('PRAGMA synchronous=FULL')
  self.db.executescript('''CREATE TABLE IF NOT EXISTS events(uid TEXT PRIMARY KEY,payload TEXT NOT NULL);
   CREATE TABLE IF NOT EXISTS snapshot(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL,hash TEXT NOT NULL);
   CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY,payload TEXT NOT NULL,status TEXT NOT NULL);''')
 def process(self,sim,e,fail_before_commit=False):
  raw=json.dumps(asdict(e),sort_keys=True)
  old=self.db.execute('SELECT payload FROM events WHERE uid=?',(e.uid(),)).fetchone()
  if old:
   if old[0]!=raw: raise ValueError('Conflicting duplicate persisted event')
   return False
  before=snapshot(sim)
  try:
   with self.db:
    self.db.execute('INSERT INTO events VALUES(?,?)',(e.uid(),raw))
    sim.process(e)
    state=snapshot(sim); payload=json.dumps(state,sort_keys=True,allow_nan=False)
    self.db.execute('INSERT OR REPLACE INTO snapshot VALUES(1,?,?)',(payload,digest(state)))
    if fail_before_commit: raise RuntimeError('Injected crash before commit')
  except BaseException:
   rebuilt=restore(sim.cfg,before); sim.__dict__.update(rebuilt.__dict__); raise
  return True
 def load(self,cfg):
  row=self.db.execute('SELECT payload,hash FROM snapshot WHERE id=1').fetchone()
  if not row: return None
  state=json.loads(row[0])
  if digest(state)!=row[1]: raise ValueError('Corrupted persisted snapshot')
  return restore(cfg,state)
 def close(self): self.db.close()

class SafeOutbox:
 """Adapter-neutral reliability contract tested with a FAKE venue, not a live broker.
 UNKNOWN after timeout must be queried, never resent without reconciliation.
 """
 def __init__(self,store): self.db=store.db
 def send(self,client_id,payload,venue):
  serialized=json.dumps(payload,sort_keys=True)
  row=self.db.execute('SELECT payload,status FROM outbox WHERE id=?',(client_id,)).fetchone()
  if row:
   if row[0]!=serialized: raise ValueError('Same client ID with different order')
   return self.reconcile(client_id,venue)
  with self.db: self.db.execute('INSERT INTO outbox VALUES(?,?,?)',(client_id,serialized,'SUBMITTING'))
  try: status=venue.submit(client_id,payload)
  except TimeoutError: status='UNKNOWN'
  with self.db: self.db.execute('UPDATE outbox SET status=? WHERE id=?',(status,client_id))
  return status
 def reconcile(self,client_id,venue):
  status=venue.query(client_id)
  # NOT_FOUND is not permission for an automatic retry; late acceptance may exist.
  status=status if status is not None else 'UNKNOWN'
  with self.db: self.db.execute('UPDATE outbox SET status=? WHERE id=?',(status,client_id))
  return status

def reconcile_protections(positions,protections):
 """Explicit findings: caller must block entries on any discrepancy."""
 findings=[]
 for p in positions:
  covered=sum(x['qty'] for x in protections if x.get('position_id')==p['id'] and x.get('reduce_only') and x.get('active') and x.get('side')==-p['side'])
  if covered+1e-10<p['remaining']: findings.append({'position_id':p['id'],'reason':'missing_stop_coverage','uncovered_qty':p['remaining']-covered})
 return findings
