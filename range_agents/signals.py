"""Shared causal event interpretation, independent of portfolios or order execution.

A breakout/re-entry observation is not a filled trade. No OHLC path is inferred.
Only the current event and state accumulated from earlier observations are used.
"""
from __future__ import annotations
from copy import deepcopy
from .config import TF_MS, threshold_pct, agent_config, digest
from .geometry import stop_plan


def signal_settings(cfg: dict, tf: str) -> dict:
    return {**cfg['signal'], **cfg.get('signal_timeframe_overrides', {}).get(tf, {})}


def window_expired(ep, ts: int, settings: dict) -> bool:
    if not ep.cycle_side or ep.break_ms is None:
        return False
    if settings['reintegration_window'] == 'same_candle':
        return ts // TF_MS[ep.range.tf] != ep.break_bucket
    return ts - ep.break_ms > settings['max_reintegration_ms']


def excursion_features(ep, ts: int, price: float) -> dict:
    if ep.break_ms is None or ep.excursion_extreme is None:
        return {'excursion_available': 0}
    side = ep.cycle_side or ep.rearm_side
    boundary = ep.range.upper if side == 1 else ep.range.lower
    elapsed = ts - ep.break_ms
    retreat_ms = ts - ep.excursion_extreme_ms
    retreat_pct = max(0., side * (ep.excursion_extreme - price) / ep.excursion_extreme * 100)
    return {'excursion_available': 1, 'break_timestamp_ms': ep.break_ms,
            'excursion_extreme': ep.excursion_extreme,
            'extreme_timestamp_ms': ep.excursion_extreme_ms,
            'excursion_elapsed_ms': elapsed,
            'max_outside_pct': max(0., side * (ep.excursion_extreme / boundary - 1) * 100),
            'retreat_from_extreme_pct': retreat_pct,
            'return_speed_pct_per_second': retreat_pct / (retreat_ms / 1000) if retreat_ms > 0 else None,
            'raw_reentries': ep.raw_reentries,
            'same_structure_candle': int(ts // TF_MS[ep.range.tf] == ep.break_bucket)}


def advance_episode(ep, event, cfg: dict, *, attempts: int | None = None,
                    enforce_attempt_limit: bool = True) -> dict | None:
    """Update one episode using ONE actually observed event.

    Pure observation can retain subsequent eligible crossings beyond the order
    budget. The simulator alone enforces that budget. No fictitious transaction.
    """
    r = ep.range
    s = signal_settings(cfg, r.tf)
    source_kind = 'trade' if s['trigger_source'] == 'last' else 'mark'
    if (event.kind != source_kind or event.symbol != r.symbol or ep.ended or
            event.ts < r.known_ms or event.ts >= r.expiry_ms):
        return None
    price, ts = event.price, event.ts
    if attempts is not None:
        ep.attempts = attempts
    if window_expired(ep, ts, s):
        ep.rearm_side, ep.cycle_side, ep.waiting_rearm = ep.cycle_side, 0, True
        ep.last_signal_ms = ts
        return {'kind': 'cycle_expired', 'timestamp_ms': ts, 'range_id': r.id}
    if ep.cycle_side:
        if ep.excursion_extreme is None or ep.cycle_side * (price - ep.excursion_extreme) > 0:
            ep.excursion_extreme, ep.excursion_extreme_ms = price, ts
        raw_outside = price > r.upper if ep.cycle_side == 1 else price < r.lower
        if ep.last_outside and not raw_outside:
            ep.raw_reentries += 1
        ep.last_outside = raw_outside
        threshold = (r.upper * (1 - s['reintegration_pct'] / 100) if ep.cycle_side == 1
                     else r.lower * (1 + s['reintegration_pct'] / 100))
        crossed = price <= threshold if ep.cycle_side == 1 else price >= threshold
        if crossed and r.lower < price < r.upper:
            path = excursion_features(ep, ts, price)
            side = -ep.cycle_side
            ep.rearm_side, ep.cycle_side, ep.waiting_rearm = ep.cycle_side, 0, True
            ep.last_signal_ms = ts
            return {'kind': 'reintegration', 'side': side, 'threshold': threshold,
                    'path': path, 'timestamp_ms': ts}
        if crossed and not r.lower < price < r.upper:
            # A jump across the entire box is not an observed print INSIDE it.
            return {'kind': 'gap_across_range', 'timestamp_ms': ts, 'range_id': r.id}
        return None
    if ep.waiting_rearm:
        threshold = (r.upper * (1 - s['rearm_pct'] / 100) if ep.rearm_side == 1
                     else r.lower * (1 + s['rearm_pct'] / 100))
        passed = price <= threshold if ep.rearm_side == 1 else price >= threshold
        if r.lower < price < r.upper and passed and ts - ep.last_signal_ms >= s['cooldown_ms']:
            ep.waiting_rearm = False
            return {'kind': 'rearmed', 'timestamp_ms': ts, 'range_id': r.id}
        return None
    if enforce_attempt_limit and ep.attempts >= s['max_breakouts_per_range']:
        return None
    if ts - ep.last_signal_ms < s['cooldown_ms']:
        return None
    pct = threshold_pct(s['breakout_mode'], s['breakout_pct'], r.volatility_pct,
                        r.width_pct, s['breakout_vol_multiplier'], s['breakout_range_fraction'],
                        s['breakout_min_pct'], s['breakout_max_pct'])
    upper, lower = r.upper * (1 + pct / 100), r.lower * (1 - pct / 100)
    side = 1 if price >= upper else -1 if price <= lower else 0
    if not side:
        return None
    ep.attempts += 1
    ep.cycle_side, ep.break_bucket, ep.last_signal_ms = side, ts // TF_MS[r.tf], ts
    ep.break_ms, ep.break_price = ts, price
    ep.excursion_extreme, ep.excursion_extreme_ms = price, ts
    ep.raw_reentries, ep.last_outside = 0, True
    return {'kind': 'breakout', 'side': side, 'threshold': upper if side == 1 else lower,
            'path': excursion_features(ep, ts, price), 'timestamp_ms': ts}


def build_signal(ep, observation: dict, event, cfg: dict, run_id: str) -> dict:
    """Immutable snapshot of decision inputs; no future labels in feature dict."""
    r, agent, side = ep.range, observation['kind'], observation['side']
    a = agent_config(cfg, agent, r.tf)
    path = deepcopy(observation.get('path', {}))
    plan = stop_plan(side, event.price, a, lower=r.lower, upper=r.upper,
                     volatility_pct=r.volatility_pct, width_pct=r.width_pct,
                     excursion_extreme=path.get('excursion_extreme') if agent == 'reintegration' else None,
                     reference_boundary=(r.upper if side == 1 else r.lower) if agent == 'breakout'
                                        else (r.lower if side == 1 else r.upper))
    pct = plan.get('distance_pct', a['stop_pct'])
    if plan.get('valid'):
        a['stop_pct'] = pct
    threshold = observation['threshold']
    features = {'width_pct': r.width_pct, 'volatility_pct': r.volatility_pct, 'bars': r.bars,
                'alternations': r.alternations, 'drift': r.drift, 'boundary_shift': r.boundary_shift,
                'width_tr_ratio': r.width_tr_ratio, 'side': side,
                'timeframe_hours': TF_MS[r.tf] / 3600000, 'stop_pct': pct,
                'overshoot_pct': abs(event.price / threshold - 1) * 100}
    features.update(deepcopy(r.context))
    features.update(path)
    return {'id': digest([run_id, event.ts, event.seq, r.id, agent, side, ep.attempts])[:24],
            'timestamp_ms': event.ts, 'event_seq': event.seq, 'symbol': event.symbol,
            'tf': r.tf, 'agent': agent, 'side': side, 'range_id': r.id, 'family': ep.family,
            'range_start_ms': r.start_ms, 'range_known_ms': r.known_ms, 'range_expiry_ms':r.expiry_ms,
            'threshold': threshold, 'observed_price': event.price,
            'observed_source': event.source, 'params': a, 'stop_pct': pct, 'stop_plan': plan,
            'accepted': False, 'reason': 'unprocessed', 'execution_status': 'NONE',
            'sfp_status': ('INTRABAR_NOT_CLOSE_CONFIRMED' if agent == 'reintegration' else 'NA'),
            'reintegration_window': signal_settings(cfg, r.tf)['reintegration_window'],
            'features': features, 'feature_known_ms': event.ts,
            'feature_snapshot_hash': digest(features)}
