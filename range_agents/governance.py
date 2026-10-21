"""Global audit of viewed periods and research attempts, independent of file layout.

Date overlap is deliberately conservative across crypto symbols and datasets.
A new ZIP, added file, or renamed directory does not make dates unseen again.
This local journal is not protection against deliberate deletion/tampering.
"""
from __future__ import annotations
from pathlib import Path
import json
import sqlite3
import time
from .config import digest

PROJECT_SCOPE = 'RANGE_AGENTS_CRYPTO'


class ResearchRegistry:
    def __init__(self, path=None):
        path = Path(path) if path is not None else Path.home()/'.range_agents'/'studies.sqlite'
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(path, timeout=15)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS accesses_v3(
          id INTEGER PRIMARY KEY, scope TEXT NOT NULL, a INTEGER NOT NULL, b INTEGER NOT NULL,
          kind TEXT NOT NULL, dataset TEXT NOT NULL, purpose TEXT NOT NULL, at INTEGER NOT NULL,
          legacy_key TEXT UNIQUE);
        CREATE INDEX IF NOT EXISTS access_period ON accesses_v3(scope,a,b);
        CREATE TABLE IF NOT EXISTS reservations_v3(
          id TEXT PRIMARY KEY, scope TEXT NOT NULL, a INTEGER NOT NULL,b INTEGER NOT NULL,
          spec TEXT NOT NULL, created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS hypotheses_v3(
          id TEXT PRIMARY KEY, spec TEXT NOT NULL, integrity TEXT NOT NULL, created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS experiments_v3(
          id TEXT PRIMARY KEY, hypothesis TEXT NOT NULL,dataset TEXT NOT NULL,code TEXT NOT NULL,
          config TEXT NOT NULL,a INTEGER NOT NULL,b INTEGER NOT NULL,status TEXT NOT NULL,created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS experiment_events_v3(
          id INTEGER PRIMARY KEY,experiment TEXT NOT NULL,status TEXT NOT NULL,payload TEXT NOT NULL,at INTEGER NOT NULL);
        ''')
        # Preserve legacy opened periods even if their old dataset fingerprint changes.
        exists=self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='holdouts'").fetchone()
        if exists:
            with self.db:
                for dataset,a,b,proposal,opened in self.db.execute('SELECT dataset,a,b,proposal,opened FROM holdouts').fetchall():
                    key=digest([dataset,a,b,proposal,opened])
                    self.db.execute('INSERT OR IGNORE INTO accesses_v3(scope,a,b,kind,dataset,purpose,at,legacy_key) VALUES(?,?,?,?,?,?,?,?)',
                        (PROJECT_SCOPE,a,b,'holdout',dataset,'legacy_v2:'+proposal,opened,key))

    @staticmethod
    def _interval(a, b):
        if not isinstance(a,int) or not isinstance(b,int) or isinstance(a,bool) or isinstance(b,bool) or a<0 or a>=b:
            raise ValueError('Intervalle UTC [a,b) invalide')

    def exposures(self, a, b):
        self._interval(a,b)
        return [dict(zip(('kind','start_ms','end_ms','dataset','purpose'),r)) for r in self.db.execute(
            'SELECT kind,a,b,dataset,purpose FROM accesses_v3 WHERE scope=? AND a<? AND b>? ORDER BY a,id',
            (PROJECT_SCOPE,b,a))]

    def record_access(self, dataset, a, b, kind, purpose):
        self._interval(a,b)
        if kind not in ('observation','development','calibration','validation','analysis'):
            raise ValueError('Use claim_holdout for a final period')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            reserved=self.db.execute('SELECT id FROM reservations_v3 WHERE scope=? AND a<? AND b>?',
                                     (PROJECT_SCOPE,b,a)).fetchone()
            if reserved:
                raise ValueError('Période finale réservée : ne pas la lire via un autre mode')
            self.db.execute('INSERT INTO accesses_v3(scope,a,b,kind,dataset,purpose,at) VALUES(?,?,?,?,?,?,?)',
                            (PROJECT_SCOPE,a,b,kind,str(dataset),str(purpose),int(time.time())))

    def reserve_holdout(self, reservation_id, a, b, specification):
        self._interval(a,b)
        raw=json.dumps(specification,sort_keys=True,allow_nan=False)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            old=self.db.execute('SELECT a,b,spec FROM reservations_v3 WHERE id=?',(reservation_id,)).fetchone()
            if old:
                if old!=(a,b,raw): raise ValueError('Réservation finale modifiée')
                return
            if self.exposures(a,b): raise ValueError('Dates déjà consultées : pas de nouveau test final aveugle')
            self.db.execute('INSERT INTO reservations_v3 VALUES(?,?,?,?,?,?)',
                            (reservation_id,PROJECT_SCOPE,a,b,raw,int(time.time())))

    def claim_holdout(self, dataset, a, b, proposal):
        self._interval(a,b)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if self.exposures(a,b):
                raise ValueError('Période finale déjà consultée/chevauchante, même avec de nouveaux fichiers')
            # Mark it opened BEFORE consuming prices. A failed run does not make it unseen.
            self.db.execute('INSERT INTO accesses_v3(scope,a,b,kind,dataset,purpose,at) VALUES(?,?,?,?,?,?,?)',
                            (PROJECT_SCOPE,a,b,'holdout',str(dataset),str(proposal),int(time.time())))

    def register_hypothesis(self, hypothesis: dict):
        required={'id','change','metrics','baseline','scope'}
        if not required<=set(hypothesis) or not all(hypothesis[k] for k in required):
            raise ValueError('Hypothèse préenregistrée incomplète')
        raw=json.dumps(hypothesis,sort_keys=True,allow_nan=False)
        with self.db:
            old=self.db.execute('SELECT spec FROM hypotheses_v3 WHERE id=?',(hypothesis['id'],)).fetchone()
            if old and old[0]!=raw: raise ValueError('Hypothèse déjà examinée : versionner, ne pas écraser')
            self.db.execute('INSERT OR IGNORE INTO hypotheses_v3 VALUES(?,?,?,?)',
                            (hypothesis['id'],raw,digest(hypothesis),int(time.time())))

    def start_experiment(self, experiment_id, hypothesis_id, dataset, code_hash, config_hash, a, b):
        self._interval(a,b)
        with self.db:
            if not self.db.execute('SELECT 1 FROM hypotheses_v3 WHERE id=?',(hypothesis_id,)).fetchone():
                raise ValueError('Hypothèse non préenregistrée')
            self.db.execute('INSERT INTO experiments_v3 VALUES(?,?,?,?,?,?,?,?,?)',
                (experiment_id,hypothesis_id,dataset,code_hash,config_hash,a,b,'RUNNING',int(time.time())))

    def append_result(self, experiment_id, status, result):
        if status not in ('TRIAL','COMPLETED','FAILED','INTERRUPTED','NO_ELIGIBLE_CANDIDATE'):
            raise ValueError('Statut inconnu')
        raw=json.dumps(result,sort_keys=True,allow_nan=False)
        with self.db:
            if not self.db.execute('SELECT 1 FROM experiments_v3 WHERE id=?',(experiment_id,)).fetchone():
                raise ValueError('Expérience inconnue')
            self.db.execute('INSERT INTO experiment_events_v3(experiment,status,payload,at) VALUES(?,?,?,?)',
                            (experiment_id,status,raw,int(time.time())))
            if status!='TRIAL':
                self.db.execute('UPDATE experiments_v3 SET status=? WHERE id=?',(status,experiment_id))

    def summary(self):
        return {'registry_path':str(self.path),'scope':PROJECT_SCOPE,
                'viewed_period_entries':self.db.execute('SELECT COUNT(*) FROM accesses_v3').fetchone()[0],
                'hypotheses':self.db.execute('SELECT COUNT(*) FROM hypotheses_v3').fetchone()[0],
                'experiments':self.db.execute('SELECT COUNT(*) FROM experiments_v3').fetchone()[0],
                'trials_ever_recorded':self.db.execute("SELECT COUNT(*) FROM experiment_events_v3 WHERE status='TRIAL'").fetchone()[0],
                'warning':'Local journal; cannot account for unknown external research or survive deliberate deletion.'}

    def close(self):
        self.db.close()

    def __enter__(self): return self
    def __exit__(self,*_): self.close()
