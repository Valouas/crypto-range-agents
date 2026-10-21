"""Permissions, metadata and interval ledger only. No fabricated market stream."""
from copy import deepcopy
from pathlib import Path
import ast
import json
import sqlite3
import subprocess
import sys
import pytest
from range_agents.config import DEFAULT
from range_agents.policy import read_policy,check_permission
from range_agents.governance import ResearchRegistry
from range_agents.observation import validate_receipt_identity,RealDataset,observe
from range_agents.observed_paths import merge_intervals

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('capability',['backtest','training','paper','synthetic_market','live_orders'])
def test_delivered_policy_blocks_experiments(capability):
    with pytest.raises(PermissionError):check_permission(capability,read_policy())


@pytest.mark.parametrize('capability',['observation','static_checks','public_collection'])
def test_only_safe_capabilities_enabled(capability):
    check_permission(capability,read_policy())


def test_live_orders_never_available_even_with_changed_policy():
    with pytest.raises(PermissionError):check_permission('live_orders',{'capabilities':{'live_orders':True}})


def test_no_authorization_boolean_shortcut():
    with pytest.raises(PermissionError):check_permission('backtest',{'capabilities':{'backtest':True},'manual_authorization':True})


def test_unknown_capability_refused():
    with pytest.raises(PermissionError):check_permission('trade_anyway',{'capabilities':{'trade_anyway':True}})


def test_simulator_refused_before_creating_account():
    from range_agents.engine import Simulator
    raw=Simulator.__new__(Simulator)
    with pytest.raises(PermissionError):raw.__init__(deepcopy(DEFAULT))
    assert not hasattr(raw,'cash') and not hasattr(raw,'positions')


def test_training_denied_before_estimator_import_or_fit():
    from range_agents.learning import fit_candidate
    with pytest.raises(PermissionError):fit_candidate([], 'breakout', 1, 3,calibration_end_ms=2)


def test_artificial_demo_denied_before_writing_market_files(tmp_path):
    from range_agents.demo import generate
    target=tmp_path/'not_created'
    with pytest.raises(PermissionError):generate(target)
    assert not target.exists()


def test_observation_import_graph_excludes_execution_and_learning():
    code="import sys; import range_agents.observation; assert 'range_agents.engine' not in sys.modules; assert 'range_agents.learning' not in sys.modules; assert 'sklearn' not in sys.modules"
    result=subprocess.run([sys.executable,'-c',code],cwd=ROOT,capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_observation_ast_has_no_portfolio_construction():
    tree=ast.parse((ROOT/'range_agents'/'observation.py').read_text(encoding='utf-8'))
    names={n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}
    assert not names & {'Simulator','Position','Order','fit_candidate','generate','counterfactuals'}


def test_no_data_never_replaced_by_demo(tmp_path):
    result=observe(tmp_path/'absent',deepcopy(DEFAULT),tmp_path/'report')
    assert result['status'].startswith('DONNEES_INSUFFISANTES')
    assert result['orders_created']==0 and result['portfolio_created'] is False
    assert result['synthetic_prices_created'] is False
    assert not (tmp_path/'report'/'candidates.jsonl.gz').exists()


def test_flag_alone_does_not_establish_provenance(tmp_path):
    (tmp_path/'manifest.json').write_text(json.dumps({'schema_version':2,'synthetic':False}))
    with pytest.raises(ValueError,match='Provenance'):RealDataset(tmp_path,deepcopy(DEFAULT))


def receipt():
    return {'url':'https://data.binance.vision/data/futures/um/monthly/klines/BTCUSDT/4h/BTCUSDT-4h-2025-01.zip',
            'name':'BTCUSDT-4h-2025-01.zip','kind':'klines','symbol':'BTCUSDT','tf':'4h','month':'2025-01',
            'verified':True,'checksum_verified_at_utc':'2026-09-21T00:00:00+00:00'}


def test_metadata_identity_check_does_not_claim_bytes_downloaded():
    validate_receipt_identity(receipt())


@pytest.mark.parametrize('field,value',[
    ('url','http://data.binance.vision/a.zip'),
    ('url','https://data.binance.vision.evil.invalid/a.zip'),
    ('url','https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/4h/BTCUSDT-4h-2025-01.zip'),
    ('symbol','ETHUSDT'),('tf','1d'),('verified',False),('checksum_verified_at_utc',None)])
def test_wrong_source_or_instrument_refused(field,value):
    r=receipt();r[field]=value
    with pytest.raises(ValueError):validate_receipt_identity(r)


def test_global_holdout_not_reset_by_new_dataset_hash(tmp_path):
    with ResearchRegistry(tmp_path/'ledger.sqlite') as r:
        r.claim_holdout('hash_v2',100,200,'proposal_A')
        with pytest.raises(ValueError):r.claim_holdout('hash_with_extra_files_v3',150,250,'proposal_B')


def test_observed_dates_cannot_be_rebranded_unseen(tmp_path):
    with ResearchRegistry(tmp_path/'ledger.sqlite') as r:
        r.record_access('raw',100,200,'observation','price catalogue')
        with pytest.raises(ValueError):r.reserve_holdout('new',150,250,{'metrics':['predeclared']})


def test_reserved_holdout_blocks_side_channel_observation(tmp_path):
    with ResearchRegistry(tmp_path/'ledger.sqlite') as r:
        r.reserve_holdout('h',100,200,{'metrics':['predeclared']})
        with pytest.raises(ValueError):r.record_access('changed',150,200,'analysis','alternate command')


def test_adjacent_half_open_intervals_are_not_overlap(tmp_path):
    with ResearchRegistry(tmp_path/'ledger.sqlite') as r:
        r.claim_holdout('A',100,200,'one');r.claim_holdout('B',200,300,'two')
        assert len(r.exposures(100,300))==2


def test_opened_state_survives_restart(tmp_path):
    path=tmp_path/'ledger.sqlite'
    with ResearchRegistry(path) as r:r.claim_holdout('A',100,200,'failed_after_open')
    with ResearchRegistry(path) as r:
        with pytest.raises(ValueError):r.claim_holdout('B',100,200,'retry')


def test_legacy_ledger_migration_preserves_seen_dates(tmp_path):
    path=tmp_path/'ledger.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE holdouts(dataset TEXT,a INTEGER,b INTEGER,proposal TEXT,opened INTEGER)')
        db.execute('INSERT INTO holdouts VALUES(?,?,?,?,?)',('old',100,200,'v2',1))
    with ResearchRegistry(path) as r:
        with pytest.raises(ValueError):r.claim_holdout('new',150,180,'v3')
        assert len(r.exposures(100,200))==1
    with ResearchRegistry(path) as r:assert len(r.exposures(100,200))==1


def test_hypothesis_spec_cannot_be_silently_changed(tmp_path):
    h={'id':'H1','change':'schema-only','metrics':['logic'],'baseline':'B','scope':['BTC']}
    with ResearchRegistry(tmp_path/'ledger.sqlite') as r:
        r.register_hypothesis(h)
        with pytest.raises(ValueError):r.register_hypothesis({**h,'metrics':['different']})


def test_negative_or_failed_attempt_retained(tmp_path):
    with ResearchRegistry(tmp_path/'ledger.sqlite') as r:
        r.register_hypothesis({'id':'H1','change':'schema-only','metrics':['logic'],'baseline':'B','scope':['metadata']})
        r.start_experiment('E1','H1','hash','code','config',100,200)
        r.append_result('E1','FAILED',{'reason':'no data; no strategy executed'})
        assert r.summary()['experiments']==1
        assert r.db.execute('SELECT status FROM experiments_v3').fetchone()[0]=='FAILED'


@pytest.mark.parametrize('a,b',[(100,100),(200,100),(-1,100),(True,100),(1.5,100)])
def test_invalid_period_metadata(a,b,tmp_path):
    with ResearchRegistry(tmp_path/'ledger.sqlite') as r:
        with pytest.raises(ValueError):r.record_access('hash',a,b,'analysis','test metadata')


def test_collection_interval_merge_is_outcome_independent():
    assert merge_intervals([(10,20),(15,30),(40,50),(30,40)])==[[10,50]]


def test_cli_backtest_denied_without_reading_nonexistent_data(tmp_path):
    p=subprocess.run([sys.executable,'-m','range_agents','backtest','--config','absent.json','--data',str(tmp_path/'absent')],cwd=ROOT,capture_output=True,text=True)
    assert p.returncode==4 and 'POLITIQUE' in p.stderr
    assert not (tmp_path/'absent').exists()
