"""Ranking only among proposals ALREADY observed; never waits for another symbol."""
from __future__ import annotations
import math
from collections import defaultdict, deque
from .config import TF_MS


def order_available(signals: list, cfg: dict, models: dict, now_ms: int) -> list:
    policy=cfg['allocation'];priority={v:i for i,v in enumerate(policy['agent_priority'])}
    known_ids=[s['id'] for s in signals]
    if any(s['timestamp_ms']>now_ms or s['range_known_ms']>now_ms for s in signals):
        raise ValueError('Cannot prioritize a future proposal')
    for s in signals:
        model=models.get((s['symbol'],s['tf'],s['agent']),models.get(s['agent']))
        decision=model.assess(s['features'],now_ms) if model is not None else None
        if decision is not None:s['model_decision']=decision
        s['allocation']={'mode':policy['mode'],'available_at_ms':now_ms,
            'available_signal_ids':known_ids,'waited_for_future_signal':False,
            'fixed_priority_rank':priority[f"{s['agent']}:{s['tf']}"]}
    if policy['mode']=='sequential':return signals
    def key(s):
        prior=priority[f"{s['agent']}:{s['tf']}"]
        if policy['mode']=='precommitted':return (prior,s['id'])
        d=s.get('model_decision',{})
        ev=d.get('expected_net_r') if d.get('status')=='MODEL' else None
        # Estimated net value already contains costs: never subtract them again.
        return (ev is None,-ev if ev is not None else 0.,prior,s['id'])
    return sorted(signals,key=key)


def correlation_timeline(structures: dict, settings: dict):
    """Closed, time-aligned observations only; never forward-fill a missing return."""
    if not settings['correlation_enabled']:return []
    tf=settings['correlation_tf'];duration=TF_MS[tf]
    publications=defaultdict(dict)
    for (symbol,frame),bars in structures.items():
        if frame!=tf:continue
        previous=None
        for row in bars.itertuples(index=False):
            ts=int(row.timestamp_ms)
            if previous is not None and ts-previous[0]==duration:
                publications[ts+duration][symbol]=math.log(float(row.close)/previous[1])
            previous=(ts,float(row.close))
    history=defaultdict(lambda:deque(maxlen=settings['correlation_lookback']))
    out=[]
    for ts,returns in sorted(publications.items()):
        for symbol,value in returns.items():history[symbol].append((ts,value))
        symbols=sorted(history);pairs={}
        for i,left in enumerate(symbols):
            la={t:v for t,v in history[left] if ts-t<settings['correlation_lookback']*duration}
            for right in symbols[i+1:]:
                rb={t:v for t,v in history[right] if ts-t<settings['correlation_lookback']*duration}
                common=sorted(set(la)&set(rb))
                if len(common)<settings['correlation_min_pairs']:continue
                av=[la[t] for t in common];bv=[rb[t] for t in common]
                am=sum(av)/len(av);bm=sum(bv)/len(bv)
                va=sum((x-am)**2 for x in av);vb=sum((x-bm)**2 for x in bv)
                if va<=0 or vb<=0:continue
                corr=sum((x-am)*(y-bm) for x,y in zip(av,bv))/math.sqrt(va*vb)
                pairs[left+'|'+right]={'correlation':max(-1.,min(1.,corr)),
                                     'pairs':len(common),'last_pair_ms':common[-1]}
        out.append({'known_ms':ts,'pairs':pairs,'tf':tf})
    return out


def correlation_admission(symbol: str, side: int, risk: float, reservations: dict,
                          snapshot: dict | None, now_ms: int, cfg: dict, base_equity: float) -> dict:
    a=cfg['allocation']
    if not a['correlation_enabled']:return {'allowed':True,'status':'DISABLED'}
    if snapshot is None or snapshot['known_ms']>now_ms or now_ms-snapshot['known_ms']>TF_MS[a['correlation_tf']]:
        return {'allowed':a['missing_correlation_policy']=='diagnostic_only','status':'CORRELATION_UNKNOWN'}
    used=risk;unknown=[]
    for r in reservations.values():
        other=r.get('symbol')
        if other==symbol:
            # Two legs can exit separately; do not deduct opposite risk.
            used+=r['risk'];continue
        entry=snapshot['pairs'].get('|'.join(sorted((symbol,str(other)))))
        if entry is None or now_ms-entry['last_pair_ms']>TF_MS[a['correlation_tf']]:
            unknown.append(other);continue
        if entry['correlation']*side*r['side']>=a['correlation_threshold']:
            used+=r['risk']
    ok=used<=base_equity*a['max_correlated_risk_pct']/100+1e-10
    if unknown and a['missing_correlation_policy']=='abstain':ok=False
    return {'allowed':ok,'status':'CORRELATION_CHECK','risk_usd':used,'unknown_symbols':unknown,
            'risk_not_netted':True,'known_ms':snapshot['known_ms']}
