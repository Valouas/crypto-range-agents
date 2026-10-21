"""Authentic data -> provenance/coverage -> causal structures and observed crossings.

This module never imports the engine, learning, or portfolio modules. It neither
constructs a position nor reconstructs an OHLC path. No historical return of a
hypothetical order is computed here.
"""
from __future__ import annotations
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import csv
import gzip
import hashlib
import heapq
import html
import itertools
import json
from urllib.parse import urlparse
import pandas as pd
from .config import TF_MS, digest, validate
from .data import sha256_file, safe_path, atomic_json, read_events, utc_ms
from .ranges import validate_structure, iter_candidate_groups, FamilyRegistry
from .types import Event, Episode
from .signals import advance_episode, build_signal
from .policy import require_capability
from .governance import ResearchRegistry
from .observed_paths import ObservedPaths
from collecte.collect_real_data import source_rows, read_vendor_checksum, positive, ms

SOURCE = 'Binance public USD-M futures archives'
BASE = 'https://data.binance.vision/data/futures/um/'
DAY = 86400000


def validate_receipt_identity(receipt: dict) -> None:
    """Metadata check only; byte verification is a separate mandatory step."""
    u = urlparse(receipt.get('url', ''))
    if u.scheme != 'https' or u.netloc != 'data.binance.vision' or u.query or u.fragment:
        raise ValueError('Source d’archive non approuvée')
    name = receipt.get('name', '')
    if receipt.get('kind') == 'klines':
        expected = f"{BASE}monthly/klines/{receipt['symbol']}/{receipt['tf']}/{receipt['symbol']}-{receipt['tf']}-{receipt['month']}.zip"
    elif receipt.get('kind') == 'aggTrades':
        expected = f"{BASE}daily/aggTrades/{receipt['symbol']}/{receipt['symbol']}-aggTrades-{receipt['day']}.zip"
    else:
        raise ValueError('Canal non pris en charge dans le mode réel strict')
    if receipt['url'] != expected or name != expected.rsplit('/',1)[-1] or receipt.get('verified') is not True:
        raise ValueError('Instrument/période/source du reçu incohérents')
    if not receipt.get('checksum_verified_at_utc'):
        raise ValueError('Date de vérification absente')


def verify_receipt(root: Path, receipt: dict) -> dict:
    validate_receipt_identity(receipt)
    archive = safe_path(root, receipt['path'])
    checksum = safe_path(root, receipt['checksum_path'])
    expected = read_vendor_checksum(checksum, receipt['name'])
    if (expected != receipt['sha256'] or sha256_file(archive) != expected
            or sha256_file(checksum) != receipt['checksum_file_sha256']):
        raise ValueError('Archive/checksum modifiés')
    return {'archive': receipt['path'], 'sha256': expected, 'url': receipt['url'],
            'checksum_sha256': receipt['checksum_file_sha256'],
            'verified_at_utc': datetime.now(timezone.utc).isoformat()}


def _verified_structure_rows(root, proofs, tf):
    step = TF_MS[tf]
    for proof in sorted(proofs, key=lambda x:x['month']):
        month_start = ms(proof['month']+'-01')
        next_month = int((pd.Timestamp(proof['month']+'-01',tz='UTC')+pd.offsets.MonthBegin()).timestamp()*1000)
        for line,row in source_rows(safe_path(root,proof['path'])):
            if len(row)!=12: raise ValueError('Source bougie : schéma inconnu')
            t=int(row[0])
            if not month_start<=t<next_month or t%step or int(row[6])!=t+step-1:
                raise ValueError('Source bougie : unité/alignement incorrects')
            o,h,l,c=map(positive,row[1:5])
            if not l<=min(o,c)<=max(o,c)<=h: raise ValueError('Source OHLC invalide')
            yield [str(t),*row[1:5]]


def verify_structure_derivation(root, item, proofs):
    """Verify every output OHLC value against original vendor decimals, not just a flag."""
    path=safe_path(root,item['path'])
    if sha256_file(path)!=item['sha256']: raise ValueError('Table structure modifiée')
    with gzip.open(path,'rt',encoding='utf-8',newline='') as f:
        rows=csv.reader(f)
        if next(rows,None)!=['timestamp_ms','open','high','low','close']:
            raise ValueError('Schéma du collecteur incompatible')
        count=0
        for expected,actual in itertools.zip_longest(_verified_structure_rows(root,proofs,item['tf']),rows):
            if expected is None or actual is None or expected!=actual:
                raise ValueError('Table non identique aux valeurs sources : aucune reconstruction acceptée')
            count+=1
    if count!=item['rows']: raise ValueError('Nombre de bougies déclaré incorrect')
    return pd.read_csv(path)


def _verified_trade_rows(root, proof):
    previous_id=previous_ts=None
    a=ms(proof['day']);b=a+DAY
    for line,row in source_rows(safe_path(root,proof['path'])):
        if len(row)!=7: raise ValueError('Schéma aggTrades inconnu')
        seq,t=int(row[0]),int(row[5])
        if not a<=t<b or seq<0 or int(row[3])>int(row[4]) or row[6].lower() not in ('true','false'):
            raise ValueError('Transaction source incorrecte')
        if previous_id is not None and (seq<=previous_id or t<previous_ts):
            raise ValueError('Ordre source incohérent')
        previous_id,previous_ts=seq,t
        yield {'ts':t,'symbol':proof['symbol'],'kind':'trade','price':float(positive(row[1])),
               'qty':float(positive(row[2])),'seq':seq,'source':'binance_public_aggTrades'}


def verify_event_derivation(root, item, proof):
    path=safe_path(root,item['path'])
    if sha256_file(path)!=item['sha256']: raise ValueError('Événements modifiés')
    count=0; first=last=previous_id=None; gap_count=0
    with gzip.open(path,'rt',encoding='utf-8') as f:
        parsed=(json.loads(line) for line in f)
        for expected,actual in itertools.zip_longest(_verified_trade_rows(root,proof),parsed):
            if expected is None or actual is None or actual!=expected:
                raise ValueError('Événement non conforme à sa transaction source')
            Event(**actual).validate()
            if previous_id is not None and actual['seq']!=previous_id+1: gap_count+=1
            previous_id=actual['seq']
            if first is None:first=actual['ts']
            last=actual['ts'];count+=1
    if not count or (count,first,last)!=(item['rows'],item['first_ms'],item['last_ms']):
        raise ValueError('Couverture transactionnelle incohérente')
    if item['requested_start_ms']!=ms(proof['day']) or item['requested_end_ms']!=ms(proof['day'])+DAY:
        raise ValueError('Période transactionnelle déclarée incorrecte')
    return {'rows':count,'first_ms':first,'last_ms':last,'id_gaps':gap_count}


class RealDataset:
    def __init__(self, root, cfg):
        require_capability('observation'); validate(cfg)
        if cfg['mode']!='observation_only': raise ValueError('Mode observation_only requis')
        self.root=Path(root);self.cfg=cfg;mp=self.root/'manifest.json'
        if not mp.exists(): raise ValueError('DONNEES_INSUFFISANTES : aucun manifeste réel reçu')
        self.manifest=json.loads(mp.read_text(encoding='utf-8'))
        m=self.manifest
        if (m.get('schema_version')!=2 or m.get('source')!=SOURCE or m.get('synthetic') is not False
                or m.get('real_data_only') is not True or m.get('generated_market_values') is not False
                or m.get('interpolated_market_values') is not False):
            raise ValueError('Provenance réelle stricte requise; un simple synthetic:false ne suffit pas')
        self.structures={};self.events_info=[];self.coverage=[];self.proofs=[];self.lineage=[]
        receipts={}
        for group in ('structure_archives','transaction_archives'):
            for item in m.get(group,[]):
                if item['name'] in receipts: raise ValueError('Reçu dupliqué')
                self.proofs.append(verify_receipt(self.root,item));receipts[item['name']]=item
        for item in m.get('structures',[]):
            key=(item['symbol'],item['tf'])
            if key[0] not in cfg['symbols'] or key[1] not in cfg['timeframes']:continue
            if key in self.structures:raise ValueError('Table structure dupliquée')
            related=[x for x in receipts.values() if x.get('kind')=='klines' and (x['symbol'],x['tf'])==key]
            if not related:raise ValueError('Structure sans archive source')
            df=validate_structure(verify_structure_derivation(self.root,item,related),key[1])
            self.structures[key]=df
            a,b=utc_ms(cfg['data_start']),utc_ms(cfg['end_exclusive']);step=TF_MS[key[1]]
            subset=df.loc[(df.timestamp_ms>=a)&(df.timestamp_ms<b)]
            for day in range(a//DAY*DAY,b,DAY):
                lo,hi=max(a,day),min(b,day+DAY)
                expected=(hi-lo)//step
                actual=int(((subset.timestamp_ms>=lo)&(subset.timestamp_ms<hi)).sum())
                self.coverage.append({'symbol':key[0],'channel':key[1],'day_utc':str(pd.Timestamp(day,unit='ms',tz='UTC').date()),
                    'observed_rows':actual,'expected_rows':expected,'missing_rows':expected-actual,
                    'status':'COMPLETE' if actual==expected else 'INCOMPLETE_NO_FILL'})
            self.lineage.append({'output':item['path'],'output_sha256':item['sha256'],
                'inputs':[{k:x[k] for k in ('url','sha256')} for x in related],
                'transform':'EXACT_VENDOR_OHLC_PROJECTION_V1','timestamp_unit':'milliseconds_utc'})
        for item in m.get('events',[]):
            if item.get('symbol') not in cfg['symbols']:continue
            if item.get('kind')!='aggTrades':raise ValueError('Canal non vérifiable avec ce collecteur strict')
            proof=item.get('archive_proof',{})
            if proof.get('name') not in receipts or proof!=receipts[proof['name']]:
                # Reverification may add cache timestamps without changing identity.
                base=receipts.get(proof.get('name'),{})
                if any(proof.get(k)!=base.get(k) for k in ('name','url','sha256','path')):raise ValueError('Filiation événement inconnue')
                proof=base
            q=verify_event_derivation(self.root,item,proof)
            self.events_info.append({**item,'quality':q})
            self.coverage.append({'symbol':item['symbol'],'channel':'aggTrades','day_utc':proof['day'],
                'observed_rows':q['rows'],'expected_rows':None,'missing_rows':None,
                'status':'SOURCE_WITH_ID_GAPS' if q['id_gaps'] else 'FULL_VENDOR_DAY_NOT_ORDER_BOOK'})
            self.lineage.append({'output':item['path'],'output_sha256':item['sha256'],
                'inputs':[{'url':proof['url'],'sha256':proof['sha256']}],
                'transform':'VENDOR_AGGTRADES_PROJECTION_FLOAT64_V1',
                'precision':'Original decimal strings remain in raw ZIP; no quotes/marks/funding fabricated'})
        self.fingerprint=digest(sorted((p['url'],p['sha256']) for p in self.proofs))
        missing=set((s,t) for s in cfg['symbols'] for t in cfg['timeframes'])-set(self.structures)
        self.missing_structures=sorted(missing)
        a,b=utc_ms(cfg['data_start']),utc_ms(cfg['end_exclusive'])
        for sym,tf in self.missing_structures:
            self.coverage.append({'symbol':sym,'channel':tf,'day_utc':'ALL_REQUESTED_PERIOD',
                'observed_rows':0,'expected_rows':(b-a)//TF_MS[tf],'missing_rows':(b-a)//TF_MS[tf],
                'status':'CHANNEL_NOT_RECEIVED'})
        present={(x['symbol'],x['requested_start_ms']//DAY) for x in self.events_info}
        self.missing_transaction_days=[]
        for sym in cfg['symbols']:
            for d in range(a//DAY,(b-1)//DAY+1):
                if (sym,d) not in present:
                    self.missing_transaction_days.append({'symbol':sym,'day_utc':str(pd.Timestamp(d*DAY,unit='ms',tz='UTC').date()),
                        'status':'NOT_COLLECTED_NO_INTRABAR_INFERENCE'})
        self._validate_channels()
        if not cfg['observation']['allow_partial_coverage'] and (missing or self.missing_transaction_days or any(x.get('missing_rows') for x in self.coverage)):
            raise ValueError('DONNEES_INSUFFISANTES : couverture complète exigée, aucun comblement autorisé')

    def _validate_channels(self):
        for sym in self.cfg['symbols']:
            rows=sorted((x for x in self.events_info if x['symbol']==sym),key=lambda x:x['requested_start_ms'])
            for a,b in zip(rows,rows[1:]):
                if b['requested_start_ms']<a['requested_end_ms']:
                    raise ValueError('Archives transactionnelles se chevauchant')

    def events(self, a, b):
        streams=[]
        for sym in self.cfg['symbols']:
            files=sorted((x for x in self.events_info if x['symbol']==sym and x['requested_start_ms']<b and x['requested_end_ms']>a),key=lambda x:x['requested_start_ms'])
            streams.append(itertools.chain.from_iterable(read_events(safe_path(self.root,x['path']),a,b) for x in files))
        return heapq.merge(*streams,key=lambda e:e.key())

    def report(self):
        missing=sum(x['missing_rows'] or 0 for x in self.coverage)
        status=('DONNEES_INSUFFISANTES' if not self.structures else
                'STRUCTURES_ONLY_INTRABAR_UNKNOWN' if not self.events_info else 'VERIFIED_REAL_DATA_PARTIAL_SCOPE')
        return {'status':status,'source':SOURCE,'fingerprint':self.fingerprint,
                'verified_archives':len(self.proofs),'structure_tables':len(self.structures),
                'missing_structures':self.missing_structures,'missing_structural_bars':missing,
                'missing_transaction_days':len(self.missing_transaction_days),
                'transaction_day_coverage':{'collected':len(self.events_info),'requested':len(self.events_info)+len(self.missing_transaction_days)},
                'event_files':len(self.events_info),'event_rows':sum(x['rows'] for x in self.events_info),
                'coverage':self.coverage,'lineage':self.lineage,'proofs':self.proofs,
                'synthetic_prices_created':False,'orders_created':0,'portfolio_created':False,
                'hypothetical_returns_computed':False,
                'unavailable_channels':self.manifest.get('unavailable_channels',[])}


def _write_csv(path, rows):
    if not rows:
        path.write_text('',encoding='utf-8');return
    keys=list(dict.fromkeys(k for r in rows for k in r))
    with path.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)


def observe(root, cfg, out):
    """Catalog on genuine received data only. Missing transactions -> UNKNOWN, not inferred."""
    require_capability('observation')
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    try:
        ds=RealDataset(root,cfg)
    except (ValueError,OSError) as exc:
        report={'status':'DONNEES_INSUFFISANTES_OR_INVALID','error':str(exc),
                'orders_created':0,'portfolio_created':False,'synthetic_prices_created':False}
        atomic_json(out/'observation.json',report)
        return report
    report=ds.report();_write_csv(out/'coverage.csv',ds.coverage)
    _write_csv(out/'missing_transaction_days.csv',ds.missing_transaction_days)
    if not ds.structures:
        atomic_json(out/'observation.json',report);return report
    a,b=utc_ms(cfg['data_start']),utc_ms(cfg['end_exclusive'])
    with ResearchRegistry() as registry:
        # Observation exposes dates too: do not later call them a blind holdout.
        registry.record_access(ds.fingerprint,a,b,'observation','causal structure/crossing catalogue')
        report['registry']=registry.summary()
    def groups():
        streams=[]
        for (symbol,tf),bars in ds.structures.items():
            selected=bars.loc[(bars.timestamp_ms>=a)&(bars.timestamp_ms+TF_MS[tf]<=b)].copy()
            streams.append(((g[0].known_ms,(g[0].symbol,g[0].tf),g)
                            for g in iter_candidate_groups(selected,symbol,tf,cfg['range'])))
        yield from heapq.merge(*streams,key=lambda x:(x[0],x[1]))
    group_iter=iter(groups());current=next(group_iter,None)
    latest={};episodes={};previous={};families=FamilyRegistry(cfg['range'])
    candidate_count=signal_count=incident_count=0;preview=[]
    with gzip.open(out/'candidates.jsonl.gz','wt',encoding='utf-8') as cf, \
         gzip.open(out/'observed_events.jsonl.gz','wt',encoding='utf-8') as ef, \
         gzip.open(out/'observed_paths_EX_POST.jsonl.gz','wt',encoding='utf-8') as pf:
        paths=ObservedPaths(cfg['observation']['horizons_seconds'],cfg['observation']['max_event_silence_ms'],lambda row:pf.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n'))
        def publish(item):
            nonlocal candidate_count
            ts,key,bank=item;latest[key]=bank[0]
            for rank,r in enumerate(bank):
                row={**r.row(),'selected_reference':rank==0,'kind':'OBSERVED_PRICE_STRUCTURE'}
                cf.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n');candidate_count+=1
        for e in ds.events(a,b):
            paths.on_event(e)
            while current and current[0]<=e.ts:
                publish(current);current=next(group_iter,None)
            old=previous.get(e.symbol)
            silence=old is not None and e.ts-old.ts>cfg['observation']['max_event_silence_ms']
            if silence:
                incident_count+=1
                for key,ep in list(episodes.items()):
                    if key[0]==e.symbol:del episodes[key]
                ef.write(json.dumps({'kind':'OBSERVATION_SILENCE','symbol':e.symbol,'timestamp_ms':e.ts,
                    'since_ms':old.ts,'meaning':'No inferred path; active excursions discarded as censored'})+'\n')
            for key,r in latest.items():
                if key[0]!=e.symbol:continue
                ep=episodes.get(key)
                if ep and e.ts>=ep.range.expiry_ms:del episodes[key];ep=None
                if ep is None and old is not None and not silence and r.known_ms<=e.ts<r.expiry_ms and r.lower<old.price<r.upper:
                    ep=Episode(r,families.family(r));episodes[key]=ep
                if ep is None:continue
                obs=advance_episode(ep,e,cfg,enforce_attempt_limit=False)
                if obs is None:continue
                if obs['kind'] not in ('breakout','reintegration'):
                    ef.write(json.dumps({**obs,'symbol':e.symbol,'tf':r.tf},ensure_ascii=False)+'\n');continue
                s=build_signal(ep,obs,e,cfg,'observation-'+ds.fingerprint[:12])
                for field in ('accepted','reason','execution_status'):s.pop(field,None)
                s.update(status='OBSERVED_CROSSING_NO_ORDER',kind=obs['kind'],hypothetical_trade_created=False)
                ef.write(json.dumps(s,ensure_ascii=False,allow_nan=False)+'\n');signal_count+=1
                paths.add(s)
                if len(preview)<100:preview.append({k:s[k] for k in ('timestamp_ms','symbol','tf','kind','side','observed_price','threshold','sfp_status')})
            previous[e.symbol]=e
        paths.finish()
        report['ex_post_observed_measurements']=paths.emitted
        while current:
            publish(current);current=next(group_iter,None)
    report.update(candidate_rows=candidate_count,observed_crossings=signal_count,
                  observation_silences=incident_count,preview=preview,
                  event_scope_warning='Only supplied continuous fine-data intervals. No inference in missing intervals or from OHLC extrema.',
                  entry_reference='Intrabar crossings; no candle-close or retest waiting',
                  pnl='NOT_COMPUTED_NO_POSITIONS')
    atomic_json(out/'observation.json',report)
    def table(rows):
        if not rows:return '<p>Aucune observation disponible pour cette section.</p>'
        keys=list(rows[0]);head=''.join('<th>'+html.escape(k)+'</th>' for k in keys)
        body=''.join('<tr>'+''.join('<td>'+html.escape(str(r.get(k,'')))+'</td>' for k in keys)+'</tr>' for r in rows)
        return '<table><thead><tr>'+head+'</tr></thead><tbody>'+body+'</tbody></table>'
    markup='<!doctype html><html lang="fr"><meta charset="utf-8"><title>Observation réelle — Range Agents V3</title><style>body{font-family:system-ui;max-width:1250px;margin:40px auto;padding:0 20px}table{border-collapse:collapse;width:100%;font-size:13px}th,td{border:1px solid #ccc;padding:7px}th{text-align:left}p{line-height:1.5}</style><h1>Observation réelle — aucun ordre</h1>'
    markup+='<p>'+html.escape(report['status'])+'. Aucun résultat de rentabilité calculé.</p>'
    markup+=f'<p>{candidate_count} candidats de structure journalisés ; {signal_count} franchissements observés. Les champs après événement ne filtrent jamais rétrospectivement une entrée.</p>'
    markup+='<h2>Événements observés (100 premiers maximum)</h2>'+table(preview)
    markup+='<h2>Couverture (200 lignes maximum, CSV complet joint)</h2>'+table(ds.coverage[:200])
    markup+='<p>Les dates consultées sont inscrites dans le registre global. Les volumes ne sont pas un filtre de signal.</p></html>'
    (out/'observation.html').write_text(markup,encoding='utf-8')
    return report
