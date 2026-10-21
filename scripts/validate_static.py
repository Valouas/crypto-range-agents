"""Only compile, validate schemas, and run the allowlisted no-market checks."""
from pathlib import Path
import compileall
import json
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from range_agents.config import load_config
from range_agents.policy import require_capability


def main():
    require_capability('static_checks')
    if not compileall.compile_dir(ROOT/'range_agents',quiet=1):return 2
    if not compileall.compile_dir(ROOT/'collecte',quiet=1):return 2
    for p in (ROOT/'configs').glob('*.json'):load_config(p)
    out=ROOT/'runs'/'static_validation';out.mkdir(parents=True,exist_ok=True)
    code=subprocess.call([sys.executable,'-m','pytest','tests_static','-q',
        '--junitxml='+str(out/'junit.xml')],cwd=ROOT)
    summary={'scope':'STATIC_SCHEMA_MATH_GUARDS_NO_MARKET_NO_POSITIONS',
             'pytest_exit_code':code,'dynamic_tests_executed':False,
             'backtest_run':False,'model_trained':False,'live_orders_sent':False}
    (out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2));return code


if __name__=='__main__':raise SystemExit(main())
