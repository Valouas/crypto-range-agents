"""Descriptive, streaming follow-up of actual prints. No entries/exits or PnL.

These are EX-POST measurements. They never feed back into features recorded at
crossing time. Missing/late data yields censored labels, not interpolated prices.
"""
from __future__ import annotations
from collections import defaultdict


class ObservedPaths:
    def __init__(self, horizons_seconds, max_silence_ms, sink, max_active_per_symbol=2000):
        if not horizons_seconds or any(not isinstance(h,int) or isinstance(h,bool) or h<=0 for h in horizons_seconds):
            raise ValueError('Positive integer horizons required')
        self.horizons=sorted(set(horizons_seconds));self.max_silence=max_silence_ms
        self.sink=sink;self.active=defaultdict(list);self.max_active=max_active_per_symbol
        self.emitted=0

    def add(self, signal):
        for h in self.horizons:
            if len(self.active[signal['symbol']])>=self.max_active:
                self._emit({'signal_id':signal['id'],'horizon_seconds':h,'status':'DIAGNOSTIC_CAP_EXCEEDED'})
                continue
            self.active[signal['symbol']].append({'signal_id':signal['id'],
                'horizon_seconds':h,'start_ms':signal['timestamp_ms'],
                'deadline_ms':signal['timestamp_ms']+h*1000,'reference_price':signal['observed_price'],
                'side':signal['side'],'last_ms':signal['timestamp_ms'],'last_seq':signal['event_seq'],
                'last_observed_price':signal['observed_price'],'favorable_observed_pct':0.,
                'adverse_observed_pct':0.,'favorable_ms':signal['timestamp_ms'],
                'had_observation_silence':False})

    def _emit(self, result):
        self.sink({**result,'use':'EX_POST_OBSERVATION_NOT_SIGNAL_FEATURE',
                   'hypothetical_return':False,'interpolated':False})
        self.emitted+=1

    def on_event(self, e):
        if e.kind!='trade':return
        keep=[]
        for x in self.active[e.symbol]:
            if e.ts<x['last_ms'] or (e.ts==x['last_ms'] and e.seq<=x['last_seq']):
                keep.append(x);continue
            if e.ts-x['last_ms']>self.max_silence:x['had_observation_silence']=True
            if e.ts<=x['deadline_ms']:
                move=x['side']*(e.price/x['reference_price']-1)*100
                if move>x['favorable_observed_pct']:
                    x['favorable_observed_pct']=move;x['favorable_ms']=e.ts
                x['adverse_observed_pct']=min(x['adverse_observed_pct'],move)
                x['last_ms']=e.ts;x['last_seq']=e.seq;x['last_observed_price']=e.price
            if e.ts>=x['deadline_ms']:
                age=x['deadline_ms']-x['last_ms']
                status='CENSORED_OBSERVATION_SILENCE' if x['had_observation_silence'] or age>self.max_silence else 'OBSERVED_PRINTS_THROUGH_HORIZON'
                self._emit({**x,'status':status,'label_available_ms':e.ts,
                    'last_observation_age_at_horizon_ms':age,
                    'last_observed_move_pct':x['side']*(x['last_observed_price']/x['reference_price']-1)*100})
            else:keep.append(x)
        self.active[e.symbol]=keep

    def finish(self):
        for rows in self.active.values():
            for x in rows:self._emit({**x,'status':'CENSORED_END_OF_SUPPLIED_OBSERVATIONS'})
        self.active.clear()


def merge_intervals(intervals):
    """Plan calendar collection windows without looking at outcomes."""
    out=[]
    for a,b in sorted(intervals):
        if not isinstance(a,int) or not isinstance(b,int) or a<0 or a>=b:raise ValueError('Invalid interval')
        if out and a<=out[-1][1]:out[-1][1]=max(out[-1][1],b)
        else:out.append([a,b])
    return out
