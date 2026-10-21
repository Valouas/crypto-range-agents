"""Calendar account metrics, not averages of independent fictitious accounts.

Called only by an explicitly authorized simulator. Never computes PnL in the
real-observation path. Missing marked-equity states stay unknown, not zero.
"""
from __future__ import annotations
from bisect import bisect_right
import math

DAY=86400000


def calendar_account_metrics(equity_log: list, trades: list, initial: float,
                             start_ms: int, end_ms: int, max_age_ms: int) -> dict:
    if end_ms<=start_ms:return {'status':'DONNEES_INSUFFISANTES','days':[]}
    states=sorted([x for x in equity_log if start_ms<=x['timestamp_ms']<=end_ms],key=lambda x:x['timestamp_ms'])
    times=[x['timestamp_ms'] for x in states]
    def at(t):
        i=bisect_right(times,t)-1
        if i<0:return initial if t==start_ms else None
        x=states[i]
        if t-x['timestamp_ms']>max_age_ms and x.get('positions',0)>0:return None
        return x['equity_usd']
    cuts=[start_ms]+list(range((start_ms//DAY+1)*DAY,end_ms,DAY))+[end_ms]
    rows=[]
    for a,b in zip(cuts,cuts[1:]):
        left,right=at(a),at(b)
        if left is None or right is None or left<=0:
            pct=None
        else:pct=100*(right/left-1)
        entries=sum(a<=t['entry_ms']<b for t in trades)
        rows.append({'start_ms':a,'end_ms':b,'return_pct':pct,'closed_trade_entries':entries,
                     'status':'KNOWN_STATE' if pct is not None else 'MARKED_STATE_UNKNOWN'})
    positive=sorted((t['net_usd'] for t in trades if t['net_usd']>0),reverse=True)
    gross_positive=sum(positive)
    final=at(end_ms)
    duration=end_ms-start_ms
    weighted_risk=weighted_gross=0.;observed_time=0
    for i,x in enumerate(states):
        until=states[i+1]['timestamp_ms'] if i+1<len(states) else end_ms
        dt=max(0,min(until,end_ms)-max(x['timestamp_ms'],start_ms))
        # Exposure is piecewise carried STATE, not an invented asset price.
        weighted_risk+=dt*x.get('risk_reserved_usd',0.)
        weighted_gross+=dt*x.get('gross_notional_usd',0.)
        observed_time+=dt
    return {'status':'CALENDAR_COMPLETE' if final is not None and all(x['return_pct'] is not None for x in rows) else 'CALENDAR_INCOMPLETE',
        'days':rows,'elapsed_days':duration/DAY,
        'total_marked_return_pct':100*(final/initial-1) if final is not None else None,
        'calendar_days_without_closed_trade_entries':sum(x['closed_trade_entries']==0 for x in rows),
        'time_mean_reserved_risk_usd':weighted_risk/observed_time if observed_time else None,
        'time_mean_gross_notional_usd':weighted_gross/observed_time if observed_time else None,
        'gross_positive_closed_pnl':gross_positive,
        'largest_winner_share_of_positive_pnl':positive[0]/gross_positive if positive else None,
        'five_largest_winners_share_of_positive_pnl':sum(positive[:5])/gross_positive if positive else None,
        'outstanding_positions_not_labelled_winners':True,
        'exposure_sampling':'PIECEWISE_RECORDED_ACCOUNT_STATE_APPROXIMATION',
        'concentration_is_diagnostic_not_automatic_rejection':True}
