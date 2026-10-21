"""Deferred acceptance tests; genuine external files only. NOT RUN for this release.

Even reading a test target here requires a separate future authorization. No test
creates market observations, model weights, execution results or fills as data.
"""
import os
from pathlib import Path
from copy import deepcopy
import json
import gzip
import pytest
from range_agents.policy import require_capability

if os.environ.get('RANGE_AGENTS_DYNAMIC_TESTS')!='AUTHORIZED':
    pytest.skip('Deferred: separate authorization and real data required',allow_module_level=True)
try:
    require_capability('backtest')
except PermissionError:
    pytest.skip('Current policy forbids dynamic experiments',allow_module_level=True)

from range_agents.config import load_config,TF_MS,digest
from range_agents.observation import RealDataset,observe
from range_agents.ranges import build_schedule
from range_agents.data import Dataset,utc_ms
from range_agents.engine import Simulator

@pytest.fixture(scope='module')
def genuine():
    root=os.environ.get('RANGE_AGENTS_REAL_DATA')
    cfgpath=os.environ.get('RANGE_AGENTS_REAL_CONFIG')
    if not root or not cfgpath:pytest.skip('Provide authentic archive root and explicit configuration')
    cfg=load_config(cfgpath)
    obs=deepcopy(cfg);obs['mode']='observation_only';obs['learning']['enabled']=False
    return Path(root),obs,RealDataset(root,obs)


def test_vendor_bytes_and_projection(genuine):
    _,_,data=genuine
    assert data.proofs and data.structures
    assert all(p['sha256'] for p in data.proofs)
    assert data.report()['hypothetical_returns_computed'] is False


def test_closed_structure_prefix_invariance(genuine):
    _,cfg,data=genuine
    tested=0
    for (symbol,tf),bars in data.structures.items():
        if len(bars)<300:continue
        # Fixed chronological cutoff, never chosen according to outcomes.
        subset=bars.iloc[:300].copy();short=subset.iloc[:220].copy()
        first=build_schedule(short,symbol,tf,cfg['range'])
        known=int(short.iloc[-1].timestamp_ms)+TF_MS[tf]
        expanded=[r for r in build_schedule(subset,symbol,tf,cfg['range']) if r.known_ms<=known]
        assert [r.row() for r in first]==[r.row() for r in expanded]
        if first:tested+=1
    if not tested:pytest.skip('No eligible structure in fixed early cutoff, not proof of success')


def test_actual_event_catalogue_has_no_orders_or_future_features(genuine,tmp_path):
    root,cfg,data=genuine
    if not data.events_info:pytest.skip('No genuine intrabar observations received')
    result=observe(root,cfg,tmp_path)
    assert result['orders_created']==0 and result['portfolio_created'] is False
    count=0
    with gzip.open(tmp_path/'observed_events.jsonl.gz','rt',encoding='utf-8') as f:
        for line in f:
            record=json.loads(line)
            if 'features' not in record:continue
            assert record['feature_known_ms']<=record['timestamp_ms']
            assert record['range_known_ms']<=record['timestamp_ms']
            assert digest(record['features'])==record['feature_snapshot_hash']
            count+=1
    if not count:pytest.skip('No observed signal: feature causality not exercised')


def test_future_authorized_portfolio_on_genuine_events(genuine):
    """Requires authorization; historical orders would still be hypothetical."""
    root,cfg,_=genuine
    explicit=load_config(os.environ['RANGE_AGENTS_REAL_CONFIG'])
    if explicit['mode']!='research_only':pytest.skip('No explicit research configuration')
    d=Dataset(root,explicit)
    a,b=utc_ms(explicit['start']),utc_ms(explicit['end_exclusive'])
    if any(x['missing_intervals'] for x in d.coverage(a,b)):
        pytest.skip('Continuous authentic event coverage missing')
    sim=Simulator(explicit,d.schedule(),a,b,'FUTURE_ACCEPTANCE_NOT_THIS_RELEASE')
    result=sim.run(d.events(a,b));assert sim.check_invariants()
    assert result['summary']['scope']=='ONE_SHARED_MULTI_ASSET_ACCOUNT'
    if not result['trades'] and not result['open_positions']:
        pytest.skip('No executions: exit/risk lifecycle not exercised')
