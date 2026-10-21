"""Economic-value filters with causal partitions and explicit abstention.

No training runs on import. The delivered runtime policy forbids training. A
candidate contains no risk/position-sizing authority and cannot self-activate.
"""
from __future__ import annotations
from copy import deepcopy
import math
import numpy as np
from .config import digest, DEFAULT
from .geometry import expected_net_value
from .policy import require_capability

FEATURES = ['width_pct', 'volatility_pct', 'bars', 'alternations', 'drift',
            'boundary_shift', 'width_tr_ratio', 'side', 'timeframe_hours',
            'stop_pct', 'overshoot_pct']
OPTIONAL_FEATURES = ['approach_observed_bars', 'approach_net_range_fraction',
                    'approach_path_range_fraction', 'near_high_close_fraction',
                    'near_low_close_fraction', 'last_close_range_fraction',
                    'recent_pullback_from_high_fraction', 'recent_pullback_from_low_fraction',
                    'next_major_high_pct', 'next_major_low_pct',
                    'next_major_high_known', 'next_major_low_known',
                    'inside_larger_candidate', 'enclosing_candidates',
                    'outer_upper_distance_pct', 'outer_lower_distance_pct',
                    'excursion_elapsed_ms', 'max_outside_pct',
                    'retreat_from_extreme_pct', 'return_speed_pct_per_second', 'raw_reentries']


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-max(-500., min(500., float(x)))))


def calibration_diagnostics(probabilities, outcomes, bins: int = 10) -> dict:
    """Reliability bins plus Brier, neither a certainty nor a profitability claim."""
    p, y = np.asarray(probabilities, float), np.asarray(outcomes, float)
    if p.ndim != 1 or y.shape != p.shape or not len(p):
        return {'status': 'DONNEES_INSUFFISANTES', 'rows': 0}
    if not np.isfinite(p).all() or not np.isfinite(y).all() or ((p < 0) | (p > 1)).any() or not set(y) <= {0., 1.}:
        raise ValueError('Probabilities/outcomes invalid')
    cells = []
    for i in range(bins):
        mask = (p >= i / bins) & (p <= (i+1)/bins if i == bins-1 else p < (i+1)/bins)
        if not mask.any():
            continue
        cells.append({'count': int(mask.sum()), 'mean_probability': float(p[mask].mean()),
                      'observed_frequency': float(y[mask].mean())})
    ece = sum(x['count'] * abs(x['mean_probability'] - x['observed_frequency']) for x in cells)/len(p)
    return {'status': 'DESCRIPTIVE', 'rows': len(p), 'bins': cells,
            'brier': float(np.mean((p-y)**2)), 'calibration_error': float(ece),
            'warning': 'Bins and Brier do not prove future calibration or independent observations.'}


class LinearFilter:
    """Retains the old class name, but V2 50%-win models are explicitly rejected."""
    def __init__(self, model: dict, require_approval: bool = True):
        body = {k: v for k, v in model.items() if k not in ('integrity', 'approval')}
        if model.get('format') != 3 or model.get('target') != 'NET_R_AFTER_ALL_COSTS':
            raise ValueError('Modèle V3 économique requis; modèle V2 non migré automatiquement.')
        if digest(body) != model.get('integrity'):
            raise ValueError('Model integrity mismatch')
        features = model.get('features', [])
        if not features or len(features) != len(set(features)) or not set(features) <= set(FEATURES + OPTIONAL_FEATURES):
            raise ValueError('Unknown/forbidden feature schema')
        n = len(features)
        for key in ('mean', 'scale', 'net_coef', 'prob_coef'):
            arr = np.asarray(model[key], float)
            if arr.shape != (n,) or not np.isfinite(arr).all():
                raise ValueError('Model vector schema invalid')
        if (np.asarray(model['scale']) <= 0).any():
            raise ValueError('Scale must be positive')
        matrix = np.asarray(model['ood_precision'], float)
        if matrix.shape != (n, n) or not np.isfinite(matrix).all():
            raise ValueError('OOD schema invalid')
        if not model['trained_before_ms'] < model['calibrated_before_ms'] < model['validated_before_ms'] < model['valid_until_ms']:
            raise ValueError('Model chronology invalid')
        if require_approval:
            approval = model.get('approval', {})
            if (model.get('synthetic') is not False or approval.get('model_integrity') != model['integrity']
                    or approval.get('scope') != 'SIMULATION_ONLY_NO_LIVE'
                    or approval.get('ack') != 'APPROUVER_MODELE_SIMULATION'):
                raise ValueError('Unapproved, altered or synthetic model cannot become active')
        self.model = deepcopy(model)
        self.threshold = float(model['decision']['min_expected_net_r'])

    def _values(self, features: dict) -> np.ndarray:
        try:
            x = np.asarray([features[k] for k in self.model['features']], float)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError('Unknown feature, no silent imputation') from exc
        if not np.isfinite(x).all():
            raise ValueError('Unknown/non-finite feature, no silent imputation')
        return (x - np.asarray(self.model['mean'])) / np.asarray(self.model['scale'])

    def estimate(self, features: dict) -> dict:
        z = self._values(features)
        m = self.model
        linear = float(z @ np.asarray(m['prob_coef']) + m['prob_intercept'])
        prob = sigmoid(m['calibration_coef'] * linear + m['calibration_intercept'])
        ridge_ev = float(z @ np.asarray(m['net_coef']) + m['net_intercept'])
        decomposed = expected_net_value(prob, m['mean_gain_net_r'], m['mean_loss_net_r'])
        ev = ridge_ev if m['objective'] == 'ridge_net_r' else decomposed
        distance = float(math.sqrt(max(0., z @ np.asarray(m['ood_precision']) @ z)))
        return {'expected_net_r': ev, 'ridge_net_r': ridge_ev,
                'decomposed_net_r': decomposed, 'probability_positive': prob,
                'model_disagreement_r': abs(ridge_ev - decomposed),
                'ood_distance': distance,
                'lower_outcome_diagnostic_r': ev + m['calibration_residual_quantile_05'],
                'lower_outcome_is_not_confidence_bound_on_mean': True,
                'fees_already_in_target': True}

    def _unknown(self, reason: str, details: dict | None = None) -> dict:
        d = self.model['decision']
        fallback = (d['unknown_policy'] == 'approved_reference'
                    and d.get('reference_fallback_approved') is True)
        return {**(details or {}), 'allowed': fallback,
                'status': 'APPROVED_REFERENCE' if fallback else 'ABSTAIN', 'reason': reason,
                'risk_multiplier': 1.0}

    def assess(self, features: dict, now_ms: int) -> dict:
        m = self.model
        if now_ms < m['validated_before_ms']:
            return self._unknown('model_not_yet_available')
        if now_ms >= m['valid_until_ms']:
            return self._unknown('model_expired')
        try:
            values = self.estimate(features)
        except ValueError:
            return self._unknown('unknown_features')
        if values['ood_distance'] > m['ood_distance_threshold']:
            return self._unknown('outside_learned_context', values)
        if m['validation_calibration']['status'] != 'DESCRIPTIVE' or m['validation_calibration']['calibration_error'] > m['decision']['max_calibration_error']:
            return self._unknown('calibration_not_accepted', values)
        if values['model_disagreement_r'] > m['decision']['max_disagreement_r']:
            return self._unknown('economic_estimators_disagree', values)
        allow = values['expected_net_r'] > self.threshold
        return {**values, 'allowed': allow, 'status': 'MODEL',
                'reason': 'positive_net_value' if allow else 'net_value_insufficient',
                'risk_multiplier': 1.0}

    def predict(self, features: dict) -> float:
        """Net R estimate, NOT a probability (format 3 prevents silent reuse)."""
        return self.estimate(features)['expected_net_r']

    def allow(self, features: dict, now_ms: int) -> bool:
        return self.assess(features, now_ms)['allowed']


def label_records(signals: list, trades: list) -> list:
    index = {s['id']: s for s in signals}
    rows = []
    for t in trades:
        s = index[t['signal_id']]
        if s.get('feature_known_ms', s['timestamp_ms']) > s['timestamp_ms'] or s['range_known_ms'] > s['timestamp_ms']:
            raise ValueError('Future feature/range in label record')
        if s.get('feature_snapshot_hash') and digest(s['features']) != s['feature_snapshot_hash']:
            raise ValueError('Feature snapshot altered after signal')
        rows.append({'timestamp_ms': s['timestamp_ms'], 'label_end_ms': t['exit_ms'],
                     'family': t['family'], 'agent': s['agent'], 'symbol': s['symbol'],
                     'features': deepcopy(s['features']), 'net_r': t['net_r'],
                     'outcome_kind': 'HYPOTHETICAL_ORDERS_NOT_EXECUTED_MARKET_TRADES'})
    return rows


def chronological_partitions(records: list, agent: str, train_end_ms: int,
                             calibration_end_ms: int, validation_end_ms: int) -> tuple:
    if not train_end_ms < calibration_end_ms < validation_end_ms:
        raise ValueError('Three ordered, distinct end dates required')
    rows = sorted((r for r in records if r['agent'] == agent), key=lambda r: (r['timestamp_ms'], r['symbol'], r['family']))
    for r in rows:
        if r['label_end_ms'] < r['timestamp_ms'] or not math.isfinite(r['net_r']):
            raise ValueError('Invalid label chronology/value')
    key = lambda r: (r['symbol'], r['family'])
    train = [r for r in rows if r['label_end_ms'] < train_end_ms]
    used = {key(r) for r in train}
    cal = [r for r in rows if train_end_ms <= r['timestamp_ms'] and r['label_end_ms'] < calibration_end_ms and key(r) not in used]
    used.update(key(r) for r in cal)
    val = [r for r in rows if calibration_end_ms <= r['timestamp_ms'] and r['label_end_ms'] < validation_end_ms and key(r) not in used]
    return train, cal, val


def fit_candidate(records, agent, train_end_ms, validation_end_ms, synthetic=False,
                  min_rows=100, *, calibration_end_ms=None, learning_cfg=None):
    require_capability('training')  # Before importing estimator libraries or reading labels.
    if synthetic:
        require_capability('synthetic_market')
    if calibration_end_ms is None:
        raise ValueError('Calibration end date required; no reuse of validation for calibration')
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression, Ridge
    lc = deepcopy(learning_cfg or DEFAULT['learning'])
    lc['min_rows'] = max(min_rows, lc['min_rows'])
    features = lc.get('features') or FEATURES
    if not features or len(set(features)) != len(features) or not set(features) <= set(FEATURES + OPTIONAL_FEATURES):
        raise ValueError('Unsupported model features')
    train, cal, val = chronological_partitions(records, agent, train_end_ms, calibration_end_ms, validation_end_ms)
    def finite_row(r):
        return all(isinstance(r['features'].get(k), (float, int)) and math.isfinite(r['features'][k]) for k in features)
    filtered = [[r for r in group if finite_row(r)] for group in (train, cal, val)]
    missing_counts = [len(a)-len(b) for a,b in zip((train,cal,val),filtered)]
    train, cal, val = filtered
    required = [lc['min_rows'], lc['min_calibration_rows'], lc['min_validation_rows']]
    for group, minimum in zip(filtered, required):
        if len(group) < minimum or len({(r['symbol'],r['family']) for r in group}) < lc['min_distinct_families']:
            raise ValueError('DONNEES_INSUFFISANTES: records/families, no forced model')
    array = lambda group: np.array([[r['features'][k] for k in features] for r in group], float)
    target = lambda group: np.array([r['net_r'] for r in group], float)
    x, yc = array(train), target(train)
    y = (yc > 0).astype(int)
    if len(set(y)) < 2 or len(set(target(cal)>0)) < 2:
        raise ValueError('Both outcomes needed for conditional value/calibration')
    scaler = StandardScaler().fit(x)  # Training only.
    z = scaler.transform(x)
    net = Ridge(alpha=1.0).fit(z, yc)
    prob = LogisticRegression(C=0.5, max_iter=2000, random_state=17).fit(z, y)
    calz = scaler.transform(array(cal))
    calibrator = LogisticRegression(C=1.0, max_iter=2000, random_state=17).fit(
        prob.decision_function(calz).reshape(-1,1), (target(cal)>0).astype(int))
    # A bounded regularized geometric distance; observations are NOT clipped/replaced.
    cov = np.atleast_2d(np.cov(z, rowvar=False)) + np.eye(len(features))*0.05
    precision = np.linalg.pinv(cov)
    distances = np.sqrt(np.maximum(0., np.einsum('ij,jk,ik->i', z, precision, z)))
    values_cal = calibrator.predict_proba(prob.decision_function(calz).reshape(-1,1))[:,1]
    gain, loss = float(yc[yc>0].mean()), float(yc[yc<=0].mean())
    cal_ev = net.predict(calz) if lc['objective']=='ridge_net_r' else values_cal*gain+(1-values_cal)*loss
    valz = scaler.transform(array(val))
    valp = calibrator.predict_proba(prob.decision_function(valz).reshape(-1,1))[:,1]
    diagnostics = calibration_diagnostics(valp, (target(val)>0).astype(int))
    body = {'format':3, 'target':'NET_R_AFTER_ALL_COSTS', 'agent':agent,
        'objective':lc['objective'], 'features':list(features),
        'mean':scaler.mean_.tolist(), 'scale':scaler.scale_.tolist(),
        'net_coef':net.coef_.tolist(), 'net_intercept':float(net.intercept_),
        'prob_coef':prob.coef_[0].tolist(), 'prob_intercept':float(prob.intercept_[0]),
        'calibration_coef':float(calibrator.coef_[0][0]),
        'calibration_intercept':float(calibrator.intercept_[0]),
        'mean_gain_net_r':gain, 'mean_loss_net_r':loss,
        'ood_precision':precision.tolist(),
        'ood_distance_threshold':max(1e-9,float(np.quantile(distances,lc['ood_quantile']))),
        'calibration_residual_quantile_05':float(np.quantile(target(cal)-cal_ev,0.05)),
        'validation_calibration':diagnostics,
        'decision':{k:lc[k] for k in ('min_expected_net_r','max_disagreement_r','unknown_policy','reference_fallback_approved','max_calibration_error')},
        'trained_before_ms':train_end_ms,'calibrated_before_ms':calibration_end_ms,
        'validated_before_ms':validation_end_ms,
        'valid_until_ms':validation_end_ms+int(lc['max_model_age_days']*86400000),
        'train_rows':len(train),'calibration_rows':len(cal),'validation_rows':len(val),
        'missing_features_excluded_by_partition':missing_counts,
        'synthetic':bool(synthetic),'record_fingerprint':digest(records),
        'validation_is_not_final_holdout':True}
    body['integrity']=digest(body)
    candidate=LinearFilter(body,require_approval=False)
    # Diagnostic at validation end: no historical orders are retroactively filtered.
    decisions=[candidate.assess(r['features'],validation_end_ms) for r in val]
    accepted=[r for r,d in zip(val,decisions) if d['allowed']]
    net_total=sum(r['net_r'] for r in accepted)
    report={'status':'CANDIDATE_NOT_APPROVED','all_validation_opportunities':len(val),
        'accepted_validation':len(accepted),'unfiltered_total_net_r':float(target(val).sum()),
        'filtered_total_net_r':net_total,'filtered_net_r_per_original_opportunity':net_total/len(val),
        'unfiltered_mean_net_r':float(target(val).mean()),
        'filtered_mean_net_r':net_total/len(accepted) if accepted else None,
        'calibration':diagnostics,
        'warning':'Labels are net outcomes; sums of R are not a shared-account return. Validation informed review, not independent final evidence.'}
    return body,report


def approve_model(model, ack, reviewer=None):
    require_capability('training')
    LinearFilter(model,require_approval=False)
    if model['synthetic']:
        raise ValueError('Synthetic model may not be approved')
    if ack!='APPROUVER_MODELE_SIMULATION' or not reviewer:
        raise ValueError('Manual acknowledgement and named reviewer required')
    from datetime import datetime,timezone
    return {**model,'approval':{'scope':'SIMULATION_ONLY_NO_LIVE','ack':ack,
        'reviewer':reviewer,'recorded_at_utc':datetime.now(timezone.utc).isoformat(),
        'model_integrity':model['integrity']}}
