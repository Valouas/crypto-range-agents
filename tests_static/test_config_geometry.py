"""Schema and scalar arithmetic checks; no candles, trajectories or positions."""
from copy import deepcopy
from pathlib import Path
import math
import pytest
from range_agents.config import DEFAULT, load_config, validate, agent_config, migrate_v2
from range_agents.geometry import active_targets, trailing_ready, expected_net_value, stop_plan, effective_stop
from range_agents.types import Rules

ROOT=Path(__file__).resolve().parents[1]


def config(): return deepcopy(DEFAULT)


@pytest.mark.parametrize('path',sorted((ROOT/'configs').glob('*.json')),ids=lambda p:p.name)
def test_supplied_configs_observation_only(path):
    c=load_config(path)
    assert c['schema_version']==3 and c['mode']=='observation_only'
    assert c['learning']['enabled'] is False


def test_reference_preserved():
    c=config();validate(c)
    assert c['signal']['same_structure_candle'] is True
    assert c['signal']['reintegration_window']=='same_candle'
    assert c['agents']['breakout']['tp1_fraction']==0.4
    assert c['agents']['breakout']['tp2_fraction']==0.3
    assert c['agents']['breakout']['breakeven_trigger_pct'] is None
    assert c['allocation']['correlation_enabled'] is False


@pytest.mark.parametrize('mode',['live','trade','auto','observation'])
def test_real_or_unknown_mode_rejected(mode):
    c=config();c['mode']=mode
    with pytest.raises(ValueError):validate(c)


@pytest.mark.parametrize('fractions,activation',[
    ((.4,.3,.3),'after_last_target'),((.4,0.,.6),'after_last_target'),
    ((0.,0.,1.),'price_pct'),((0.,0.,1.),'initial_r'),((0.,0.,1.),'immediate'),
    ((1.,0.,0.),'disabled'),((0.,1.,0.),'disabled')])
def test_exit_profiles_valid(fractions,activation):
    c=config();a=c['agents']['breakout']
    a.update(zip(('tp1_fraction','tp2_fraction','runner_fraction'),fractions));a['trailing_activation']=activation
    validate(c)
    assert len(active_targets(a))==sum(x>0 for x in fractions[:2])


@pytest.mark.parametrize('fractions',[(-.1,.3,.8),(.4,.4,.4),(0.,0.,0.),(1.1,0.,-.1)])
def test_invalid_fractions_rejected(fractions):
    c=config();c['agents']['breakout'].update(zip(('tp1_fraction','tp2_fraction','runner_fraction'),fractions))
    with pytest.raises(ValueError):validate(c)


def test_runner_without_targets_requires_explicit_activation():
    c=config();c['agents']['breakout'].update(tp1_fraction=0,tp2_fraction=0,runner_fraction=1)
    with pytest.raises(ValueError,match='activation'):validate(c)


def test_one_target_does_not_wait_for_tp2():
    a=config()['agents']['breakout'];a.update(tp2_fraction=0,runner_fraction=.6)
    assert trailing_ready(a,0,0,{'tp1'})
    assert not trailing_ready(a,100,100,set())


@pytest.mark.parametrize('mode,move,r,expected',[
    ('price_pct',1.19,9.,False),('price_pct',1.2,0.,True),
    ('initial_r',9.,1.99,False),('initial_r',0.,2.,True),
    ('immediate',0.,0.,True),('disabled',100.,100.,False)])
def test_trailing_independent_scalar_threshold(mode,move,r,expected):
    a=config()['agents']['breakout'];a['trailing_activation']=mode
    assert trailing_ready(a,move,r,set()) is expected


def test_timeframe_overrides_are_copied_and_validated():
    c=config();c['agents']['breakout']['timeframe_overrides']={'1d':{'stop_pct':.9}}
    validate(c);a=agent_config(c,'breakout','1d');a['stop_pct']=4
    assert c['agents']['breakout']['stop_pct']==.6
    assert c['agents']['breakout']['timeframe_overrides']['1d']['stop_pct']==.9


@pytest.mark.parametrize('override',[{'risk_per_trade_pct':20},{'tp1_fraction':.9},{'stop_mode':'random'},{'enabled':1}])
def test_bad_agent_overrides_cannot_bypass_validation(override):
    c=config();c['agents']['breakout']['timeframe_overrides']={'1d':override}
    with pytest.raises(ValueError):validate(c)


def test_elapsed_mode_must_be_explicit():
    c=config();c['signal']['reintegration_window']='elapsed'
    with pytest.raises(ValueError):validate(c)
    c['signal']['same_structure_candle']=False;validate(c)


def test_signal_override_cannot_redefine_risk():
    c=config();c['signal_timeframe_overrides']={'4h':{'leverage_limit':100}}
    with pytest.raises(ValueError):validate(c)


@pytest.mark.parametrize('value',[float('nan'),float('inf'),-float('inf')])
def test_nonfinite_even_nested_override_rejected(value):
    c=config();c['agents']['breakout']['timeframe_overrides']={'4h':{'runner_trail_pct':value}}
    with pytest.raises(ValueError):validate(c)


def test_unknown_context_fallback_requires_approval():
    c=config();c['learning']['unknown_policy']='approved_reference'
    with pytest.raises(ValueError):validate(c)


def test_observation_cannot_activate_learning():
    c=config();c['learning']['enabled']=True
    with pytest.raises(ValueError):validate(c)


def test_migration_is_copy_and_never_unlocks():
    old=config();old['schema_version']=2;old['mode']='paper_only'
    old['agents']['breakout']['model_path']='do_not_activate.json'
    original=deepcopy(old);new=migrate_v2(old)
    assert old==original and new['mode']=='observation_only'
    assert new['agents']['breakout']['model_path'] is None


@pytest.mark.parametrize('prob,gain,loss,expected',[(.35,3.,-1.,.4),(.8,.1,-1.,-.12),(0.,3.,-1.,-1.),(1.,3.,-1.,3.)])
def test_economic_value_not_win_rate(prob,gain,loss,expected):
    assert expected_net_value(prob,gain,loss)==pytest.approx(expected)


@pytest.mark.parametrize('args',[(1.1,3.,-1.),(.3,-3.,-1.),(.5,2.,1.),(float('nan'),2.,-1.)])
def test_invalid_economic_inputs(args):
    with pytest.raises(ValueError):expected_net_value(*args)


@pytest.mark.parametrize('side,price,expected',[(1,100.2,99.95),(-1,89.8,90.045)])
def test_frozen_boundary_geometry(side,price,expected):
    a=config()['agents']['breakout'];a['stop_mode']='boundary'
    plan=stop_plan(side,price,a,lower=90.,upper=100.,volatility_pct=1.,width_pct=10.)
    assert plan['valid'];assert plan['anchor_price']==pytest.approx(expected)
    rule=Rules(tick=.001)
    stop,pct=effective_stop(price,side,plan,a,rule)
    assert stop==pytest.approx(expected)
    assert pct==pytest.approx(side*(price-stop)/price*100)
    assert plan['anchor_price']==pytest.approx(expected)


def test_structure_too_far_is_not_clamped():
    a=config()['agents']['breakout'];a.update(stop_mode='boundary',stop_max_pct=.1)
    p=stop_plan(1,100.2,a,lower=90.,upper=100.,volatility_pct=1.,width_pct=10.)
    assert not p['valid'] and p['distance_pct']>.1


def test_excursion_requires_observed_anchor():
    a=config()['agents']['reintegration'];a['stop_mode']='excursion'
    plan=stop_plan(-1,99.9,a,lower=90.,upper=100.,volatility_pct=1.,width_pct=10.)
    assert plan['valid'] is False and plan['anchor_price'] is None


def test_excursion_anchor_not_changed_to_entry():
    a=config()['agents']['reintegration'];a['stop_mode']='excursion'
    p=stop_plan(-1,99.9,a,lower=90.,upper=100.,volatility_pct=1.,width_pct=10.,excursion_extreme=102.)
    assert p['valid'] and p['anchor_price']==pytest.approx(102.051)


def test_wrong_side_at_new_quote_rejected_without_moving_anchor():
    a=config()['agents']['breakout'];a['stop_mode']='boundary'
    p=stop_plan(1,100.2,a,lower=90.,upper=100.,volatility_pct=1.,width_pct=10.)
    original=deepcopy(p)
    with pytest.raises(ValueError):effective_stop(99.,1,p,a,Rules())
    assert p==original
