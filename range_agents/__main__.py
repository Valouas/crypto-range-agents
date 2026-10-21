"""V3 CLI: real observation by default; hypothetical experiments separately locked."""
from __future__ import annotations
import argparse
import json
import platform
import sys
from pathlib import Path
from .config import load_config, migrate_v2, digest
from .policy import read_policy, require_capability

ROOT=Path(__file__).resolve().parents[1]


def doctor(out=None):
    from importlib.metadata import version,PackageNotFoundError
    deps={}
    for name in ('numpy','pandas','requests','pytest','scikit-learn'):
        try:deps[name]=version(name)
        except PackageNotFoundError:deps[name]='MISSING'
    report={'version':'3.0.0','python':sys.version,'platform':platform.platform(),
        'python_supported':sys.version_info>=(3,11),'dependencies':deps,
        'policy':read_policy(),'live_order_connector':False,'network_tested':False,
        'note':'No hypothetical portfolio, no generated market data, no training during this command.'}
    if out:
        from .data import atomic_json
        atomic_json(out,report)
    print(json.dumps(report,indent=2,ensure_ascii=False));return report


def main(argv=None):
    ap=argparse.ArgumentParser(description='Range Agents V3 — observation réelle ; expériences verrouillées')
    sub=ap.add_subparsers(dest='cmd',required=True)
    p=sub.add_parser('doctor');p.add_argument('--out')
    p=sub.add_parser('check-config');p.add_argument('--config',default='configs/observation.json')
    p=sub.add_parser('migrate-config');p.add_argument('--input',required=True);p.add_argument('--out',required=True)
    p=sub.add_parser('collect');p.add_argument('--task',choices=['plan','structures','transactions','verify'],default='plan')
    p.add_argument('--plan',default=str(ROOT/'collecte'/'collection_plan.json'));p.add_argument('--data',default='data/reel')
    p.add_argument('--retries',type=int,choices=range(1,6),default=3)
    for cmd in ('verify-data','observe','preflight','backtest','research','compare','paper'):
        p=sub.add_parser(cmd);p.add_argument('--config',default='configs/observation.json')
        p.add_argument('--data',default='data/reel');p.add_argument('--out',default='runs/'+cmd)
        if cmd=='paper':p.add_argument('--seconds',type=int,default=300)
    p=sub.add_parser('registry-summary')
    p=sub.add_parser('train-filter');p.add_argument('--result',required=True)
    p.add_argument('--agent',required=True,choices=['breakout','reintegration'])
    for key in ('train-end','calibration-end','validation-end','out'):p.add_argument('--'+key,required=True)
    p=sub.add_parser('approve-model');p.add_argument('--model',required=True);p.add_argument('--ack',required=True)
    p.add_argument('--reviewer',required=True);p.add_argument('--out',required=True)
    p=sub.add_parser('holdout');p.add_argument('--proposal',required=True);p.add_argument('--data',required=True)
    p.add_argument('--ack',required=True);p.add_argument('--out',required=True)
    p=sub.add_parser('approve');p.add_argument('--proposal',required=True);p.add_argument('--ack',required=True);p.add_argument('--out',required=True)
    a=ap.parse_args(argv)
    try:
        if a.cmd=='doctor':doctor(a.out);return 0
        if a.cmd=='check-config':
            c=load_config(a.config)
            print(json.dumps({'status':'CONFIG_VALID','schema':3,'mode':c['mode'],'hash':digest(c),
                              'strategy_executed':False,'policy':read_policy()['capabilities']},indent=2));return 0
        if a.cmd=='migrate-config':
            source,target=Path(a.input).resolve(),Path(a.out).resolve()
            if source==target:raise ValueError('Migration vers un nouveau fichier obligatoire')
            if target.exists():raise ValueError('Fichier de sortie existant : aucun écrasement')
            c=migrate_v2(json.loads(source.read_text(encoding='utf-8-sig')))
            from .data import atomic_json
            atomic_json(target,c);print('Configuration migrée en observation_only :',target);return 0
        if a.cmd=='collect':
            require_capability('public_collection')
            from collecte.collect_real_data import load_plan,plan_summary,dataset_lock,collect,verify
            plan=load_plan(Path(a.plan))
            if a.task=='plan':print(json.dumps(plan_summary(plan),indent=2,ensure_ascii=False));return 0
            with dataset_lock(Path(a.data)):
                return verify(Path(a.data)) if a.task=='verify' else collect(plan,Path(a.data),a.task,a.retries)
        if a.cmd=='registry-summary':
            from .governance import ResearchRegistry
            with ResearchRegistry() as r:print(json.dumps(r.summary(),indent=2,ensure_ascii=False))
            return 0
        if a.cmd in ('verify-data','observe'):
            from .observation import RealDataset,observe
            c=load_config(a.config)
            if a.cmd=='observe':
                result=observe(a.data,c,a.out)
            else:
                from .data import atomic_json
                result=RealDataset(a.data,c).report();atomic_json(Path(a.out)/'quality.json',result)
            print(json.dumps({k:v for k,v in result.items() if k not in ('coverage','preview','proofs','lineage')},indent=2,ensure_ascii=False))
            return 2 if result['status'].startswith('DONNEES_INSUFFISANTES') else 0
        # No simulator/research import before permission has been established.
        capability='training' if a.cmd in ('train-filter','approve-model') else 'paper' if a.cmd=='paper' else 'backtest'
        require_capability(capability)
        from .data import Dataset,utc_ms,atomic_json
        if a.cmd=='train-filter':
            from .learning import fit_candidate,label_records
            raw=json.loads(Path(a.result).read_text(encoding='utf-8'));r=raw['result']
            m,diagnostic=fit_candidate(label_records(r['signals'],r['trades']),a.agent,
                utc_ms(a.train_end),utc_ms(a.validation_end),raw['manifest'].get('synthetic',False),
                calibration_end_ms=utc_ms(a.calibration_end))
            atomic_json(a.out,m);atomic_json(str(a.out)+'.diagnostic.json',diagnostic);return 0
        if a.cmd=='approve-model':
            from .learning import approve_model
            model=json.loads(Path(a.model).read_text(encoding='utf-8'))
            atomic_json(a.out,approve_model(model,a.ack,a.reviewer));return 0
        if a.cmd in ('holdout','approve'):
            from .research import holdout,approve
            proposal=json.loads(Path(a.proposal).read_text(encoding='utf-8'))
            if a.cmd=='approve':atomic_json(a.out,approve(proposal,a.ack));return 0
            if a.ack!='OUVRIR_TEST_FINAL_UNE_FOIS':raise ValueError('Accord d’ouverture finale requis')
            dataset=Dataset(a.data,proposal['candidate_config'])
            atomic_json(a.out,holdout(dataset,proposal));return 0
        c=load_config(a.config)
        if a.cmd=='paper':
            from .paper import run_paper
            run_paper(c,a.out,a.seconds);return 0
        if c['mode']!='research_only':raise ValueError('Mode recherche non activé explicitement')
        from .research import folds,preflight,run_partition,research,compare_baseline
        d=Dataset(a.data,c);fs,ho=folds(c);start=utc_ms(c['start']);end=ho[0]
        if a.cmd=='preflight':result=preflight(c,d.schedule(),d)
        elif a.cmd=='research':result=research(d,c,a.out)
        elif a.cmd=='compare':result=compare_baseline(d,c,start,end)
        else:
            if any(x['missing_intervals'] for x in d.coverage(start,end)):
                raise ValueError('Données transactionnelles incomplètes : aucun résultat sur couverture tronquée')
            result=run_partition(d,c,d.schedule(),start,end,'development-explicit')
            from .report import export_result
            export_result(result,a.out,c,d.manifest)
        atomic_json(Path(a.out)/'result.json',result);print('Résultat enregistré :',a.out);return 0
    except PermissionError as exc:
        print('BLOQUÉ PAR LA POLITIQUE : '+str(exc),file=sys.stderr);return 4
    except (ValueError,OSError,KeyError,TypeError) as exc:
        print('ARRÊT CONTRÔLÉ : '+str(exc),file=sys.stderr);return 2


if __name__=='__main__':raise SystemExit(main())
