"""Point-in-time eligibility and contract rule changes. No present-day ranking backfill."""
from __future__ import annotations
from bisect import bisect_right
from pathlib import Path
import json
from .types import Rules

class Universe:
 def __init__(self,cfg):
  self.cfg=cfg; self.rows=[]
  if cfg['kind']=='point_in_time':
   raw=json.loads(Path(cfg['snapshots_file']).read_text(encoding='utf-8'))
   for r in raw:
    if r['available_ms']<r['asof_ms']: raise ValueError('Snapshot disponible avant observation')
    if r['valid_until_ms']<=r['available_ms']: raise ValueError('Snapshot expire avant publication')
    if 'source' not in r: raise ValueError('Source du classement requise')
    self.rows.append(r)
   self.rows.sort(key=lambda r:(r['available_ms'],r['asof_ms']))
 def eligible(self,symbol,now):
  if self.cfg['kind']=='static_exploratory': return True
  # Latest WHOLE universe snapshot, not latest per-symbol (removed symbols must disappear).
  valid=[r for r in self.rows if r['available_ms']<=now<r['valid_until_ms']]
  if not valid: return False
  r=valid[-1]
  assets=sorted(r['assets'],key=lambda a:(a['rank'],a['symbol']))
  chosen=[a['symbol'] for a in assets if a.get('eligible',True)][:self.cfg['max_assets']]
  return symbol in chosen

class RuleBook:
 def __init__(self,cfg):
  self.default=cfg['rules_default']; self.static=cfg['rules']; self.rows=[]
  if cfg.get('rule_history_file'):
   self.rows=json.loads(Path(cfg['rule_history_file']).read_text(encoding='utf-8'))
   if any(r['available_ms']>r['effective_ms'] for r in self.rows):
    raise ValueError('Regles non connues a leur date effective')
 def get(self,symbol,now):
  valid=[r for r in self.rows if r['symbol']==symbol and r['available_ms']<=now and r['effective_ms']<=now<r['end_ms']]
  if self.rows and not valid: raise ValueError(f'Regles historiques absentes: {symbol} a {now}')
  rules=max(valid,key=lambda r:r['effective_ms'])['rules'] if valid else self.static.get(symbol,self.default)
  return Rules(**rules)
