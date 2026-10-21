"""Pure price/risk arithmetic. No market generator and no order or position objects."""
from __future__ import annotations
import math
from .config import threshold_pct


def active_targets(params: dict) -> list[tuple[str, float, float]]:
    return [(f'tp{i}', float(params[f'tp{i}_pct']), float(params[f'tp{i}_fraction']))
            for i in (1, 2) if params[f'tp{i}_fraction'] > 0]


def trailing_ready(params: dict, move_pct: float, move_initial_r: float,
                   completed: set[str]) -> bool:
    mode = params['trailing_activation']
    if mode == 'disabled' or params['runner_fraction'] <= 0:
        return False
    if mode == 'immediate':
        return True
    if mode == 'price_pct':
        return move_pct >= params['trailing_trigger_pct']
    if mode == 'initial_r':
        return move_initial_r >= params['trailing_trigger_r']
    if mode == 'after_last_target':
        targets = active_targets(params)
        return bool(targets) and all(name in completed for name, _, _ in targets)
    raise ValueError('Unknown trailing activation')


def stop_plan(side: int, price: float, params: dict, *, lower: float, upper: float,
              volatility_pct: float, width_pct: float,
              excursion_extreme: float | None = None,
              reference_boundary: float | None = None) -> dict:
    """Freeze a structural anchor at decision time; do NOT clamp structural distances."""
    if side not in (-1, 1) or not math.isfinite(price) or price <= 0:
        raise ValueError('Invalid stop inputs')
    mode = params['stop_mode']
    if mode == 'boundary':
        boundary = (upper if side == 1 else lower) if reference_boundary is None else reference_boundary
        if not math.isfinite(boundary) or boundary not in (lower, upper):
            raise ValueError('Structural boundary must be one of the frozen range bounds')
        anchor = boundary * (1 - side * params['stop_boundary_margin_pct'] / 100)
    elif mode == 'excursion':
        if excursion_extreme is None or not math.isfinite(excursion_extreme) or excursion_extreme <= 0:
            return {'valid': False, 'reason': 'excursion_anchor_unavailable', 'anchor_price': None}
        anchor = excursion_extreme * (1 - side * params['stop_excursion_margin_pct'] / 100)
    else:
        pct = threshold_pct(mode, params['stop_pct'], volatility_pct, width_pct,
                            params['stop_vol_multiplier'], params['stop_range_fraction'],
                            params['stop_min_pct'], params['stop_max_pct'])
        return {'valid': True, 'reason': 'distance_reference', 'anchor_price': None,
                'distance_pct': pct, 'mode': mode}
    pct = side * (price - anchor) / price * 100
    valid = (math.isfinite(anchor) and anchor > 0 and pct > 0 and
             params['stop_min_pct'] <= pct <= params['stop_max_pct'])
    return {'valid': valid, 'reason': 'structural_anchor' if valid else 'structural_distance_invalid',
            'anchor_price': anchor, 'distance_pct': pct, 'mode': mode}


def effective_stop(fill: float, side: int, plan: dict, params: dict, rules) -> tuple[float, float]:
    """Recompute risk at a quoted/filled price without moving a frozen anchor."""
    if not plan.get('valid'):
        raise ValueError(plan.get('reason', 'invalid_stop_plan'))
    anchor = plan.get('anchor_price')
    raw = float(anchor) if anchor is not None else fill * (1 - side * plan['distance_pct'] / 100)
    stop = rules.price_adverse(raw, -side)
    pct = side * (fill - stop) / fill * 100
    if not (stop > 0 and pct > 0 and params['stop_min_pct'] <= pct <= params['stop_max_pct']):
        raise ValueError('actual_structural_or_rounded_stop_outside_limits')
    return stop, pct


def expected_net_value(probability: float, mean_gain_net_r: float, mean_loss_net_r: float) -> float:
    """Outcomes are already net: do not subtract fees again, no 50% threshold."""
    if not all(math.isfinite(v) for v in (probability, mean_gain_net_r, mean_loss_net_r)):
        raise ValueError('Finite values required')
    if not 0 <= probability <= 1 or mean_gain_net_r < 0 or mean_loss_net_r > 0:
        raise ValueError('Probability or conditional outcome sign invalid')
    return probability * mean_gain_net_r + (1 - probability) * mean_loss_net_r
