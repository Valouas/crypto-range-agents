"""Configuration/metadata/scalar regressions; NO market sequence or position."""
from copy import deepcopy
from types import SimpleNamespace
from pathlib import Path
import ast
import pytest
from range_agents.config import DEFAULT,validate
from range_agents.geometry import stop_plan
from range_agents.signals import window_expired
from range_agents.research import baseline_exit_profile,apply_variant,variants
from range_agents.learning import LinearFilter
from range_agents.observed_paths import merge_intervals

ROOT=Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('side,price,boundary,expected',[
    (-1,99.9,100.,100.05),(1,90.1,90.,89.955)])
def test_reintegration_structural_boundary_is_crossed_boundary(side,price,boundary,expected):
    a=deepcopy(DEFAULT['agents']['reintegration']);a['stop_mode']='boundary'
    plan=stop_plan(side,price,a,lower=90.,upper=100.,volatility_pct=1.,width_pct=10.,reference_boundary=boundary)
    assert plan['valid'] and plan['anchor_price']==pytest.approx(expected)


def test_not_a_frozen_boundary_is_rejected():
    a=deepcopy(DEFAULT['agents']['breakout']);a['stop_mode']='boundary'
    with pytest.raises(ValueError):
        stop_plan(1,100.2,a,lower=90.,upper=100.,volatility_pct=1.,width_pct=10.,reference_boundary=99.)


def test_custom_exit_reference_is_not_silently_rewritten():
    c=deepcopy(DEFAULT);c['agents']['breakout'].update(tp1_fraction=.2,tp2_fraction=.2,runner_fraction=.6)
    assert baseline_exit_profile(c['agents']['breakout'])=='unchanged'
    c['research']['grid']={'exit.profile':['one_partial','runner_only']}
    vs=variants(c,'breakout')  # Configuration construction only; no data or engine instance.
    assert len(vs)==3
    baseline=next(cfg for _,params,cfg in vs if params['exit.profile']=='unchanged')
    assert baseline['agents']['breakout']['tp1_fraction']==.2
    assert baseline['agents']['breakout']['tp2_fraction']==.2
    assert c['mode']=='observation_only'


@pytest.mark.parametrize('profile,target_count', [('partials_reference',2),('one_partial',1),('runner_only',0)])
def test_explicit_exit_profiles_change_only_requested_agent(profile,target_count):
    c=deepcopy(DEFAULT);v=apply_variant(c,'breakout',{'exit.profile':profile})
    a=v['agents']['breakout'];assert sum(a[f'tp{i}_fraction']>0 for i in (1,2))==target_count
    assert v['agents']['reintegration']==c['agents']['reintegration']
    assert v['risk']==c['risk'] and v['mode']=='observation_only'


@pytest.mark.parametrize('grid',[
    {'risk.risk_per_trade_pct':[1]}, {'agent.leverage_limit':[50]},
    {'execution.fee_pct':[0]}, {'learning.enabled':[True]}])
def test_search_grid_cannot_optimize_risk_or_costs(grid):
    c=deepcopy(DEFAULT);c['research']['grid']=grid
    with pytest.raises(ValueError):variants(c,'breakout')


def test_grid_one_change_not_cartesian_product():
    c=deepcopy(DEFAULT);specs=variants(c,'breakout');base=specs[0][1]
    for _,params,_ in specs:assert sum(v!=base[k] for k,v in params.items())<=1


def test_same_candle_boundary_and_elapsed_are_distinct_clock_rules():
    # Metadata timestamps only; no price observations constructed.
    ep=SimpleNamespace(cycle_side=1,break_ms=86340000,break_bucket=0,range=SimpleNamespace(tf='1d'))
    s=deepcopy(DEFAULT['signal'])
    assert window_expired(ep,86460000,s)
    s.update(reintegration_window='elapsed',same_structure_candle=False,max_reintegration_ms=180000)
    assert not window_expired(ep,86460000,s)
    assert window_expired(ep,86520001,s)


@pytest.mark.parametrize('hs',[[],[60,60],[0],[True],[-1],[86401],[1.2]])
def test_invalid_observation_horizons_rejected(hs):
    c=deepcopy(DEFAULT);c['observation']['horizons_seconds']=hs
    with pytest.raises(ValueError):validate(c)


def test_reject_legacy_50percent_model_without_training():
    with pytest.raises(ValueError,match='V3'):LinearFilter({'format':2,'target':'win','threshold':.5})


def test_clock_interval_merge_has_no_outcome_selection():
    assert merge_intervals([(10,20),(15,25),(25,30),(50,60)])==[[10,30],[50,60]]


def test_original_signal_observed_price_not_overwritten_by_flip():
    tree=ast.parse((ROOT/'range_agents'/'engine.py').read_text())
    for node in ast.walk(tree):
        if isinstance(node,(ast.Assign,ast.AugAssign)):
            targets=node.targets if isinstance(node,ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target,ast.Subscript) and isinstance(target.value,ast.Name) and target.value.id=='s':
                    assert not(isinstance(target.slice,ast.Constant) and target.slice.value=='observed_price')


def test_observer_contains_no_order_or_return_simulator_imports():
    for file in ('observation.py','observed_paths.py'):
        tree=ast.parse((ROOT/'range_agents'/file).read_text())
        for n in ast.walk(tree):
            if isinstance(n,ast.ImportFrom):
                assert n.module not in ('engine','paper','research','learning','metrics')


def test_timeframe_override_is_resolved_before_variants():
    from range_agents.research import scoped_config
    c=deepcopy(DEFAULT)
    c['agents']['breakout']['timeframe_overrides']={'1d':{'stop_pct':.9}}
    c['signal_timeframe_overrides']={'1d':{'breakout_pct':.2}}
    scoped=scoped_config(c,'1d')
    assert scoped['agents']['breakout']['stop_pct']==.9
    assert scoped['signal']['breakout_pct']==.2
    changed=apply_variant(scoped,'breakout',{'agent.stop_pct':.3})
    assert changed['agents']['breakout']['stop_pct']==.3
    assert 'timeframe_overrides' not in changed['agents']['breakout']
    assert c['agents']['breakout']['timeframe_overrides']['1d']['stop_pct']==.9


def test_shared_threshold_conflict_not_silently_overwritten():
    from range_agents.research import merge_shared_threshold
    values={}
    assert merge_shared_threshold(values,'1d','breakout_pct',.1)
    assert not merge_shared_threshold(values,'1d','breakout_pct',.2)
    assert values[('1d','breakout_pct')]==.1
    assert merge_shared_threshold(values,'4h','breakout_pct',.2)


def test_reintegration_grid_respects_user_specification():
    c=deepcopy(DEFAULT);c['research']['grid']={'signal.breakout_pct':[.1,.2]}
    choices=variants(c,'reintegration')
    assert all(set(params)=={'signal.breakout_pct'} for _,params,_ in choices)
