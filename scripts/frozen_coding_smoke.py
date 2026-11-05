"""Paid frozen master/worker/reviewer run with an isolated temporary project/account data."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from jarvis.config import Settings,ROOT,USER_DIR
from jarvis.coding import git,atomic_json

def main():
    settings=Settings.load()
    with tempfile.TemporaryDirectory(prefix='jarvis-frozen-coding-') as temporary:
        base=Path(temporary);data=base/'data';project=base/'demo';project.mkdir();(project/'tests').mkdir()
        git(project,'init','-b','main')
        (project/'README.md').write_text('''Implement add(a,b) in arithmetic.py: return a+b for integers. Tests in tests/test_arithmetic.py must use unittest and cover positives, negatives, zero. No third-party dependencies. Plan exactly two independent tasks, no dependencies: one owns arithmetic.py, one owns tests/test_arithmetic.py. Run configured checks after integration.''',encoding='utf-8')
        (project/'arithmetic.py').write_text('def add(a,b):\n    raise NotImplementedError\n',encoding='utf-8')
        (project/'tests/test_arithmetic.py').write_text('import unittest\n',encoding='utf-8')
        (project/'.gitignore').write_text('__pycache__/\n',encoding='utf-8')
        git(project,'add','.');git(project,'commit','-m','Frozen demo skeleton');before=git(project,'rev-parse','HEAD')
        atomic_json(data/'projects.json',{'frozen-demo':{'path':str(project),'checks':[[sys.executable,'-m','unittest','discover','-s','tests','-v']]}})
        ident=uuid.uuid4().hex[:24]
        atomic_json(data/'coding-jobs'/ident/'request.json',{'project_id':'frozen-demo','goal':'Implement the README, exactly two independent implementation and test workers, checks and review.'})
        env={**os.environ,'JARVIS_DATA_DIR':str(data),'OPENROUTER_API_KEY':settings.api_key,
             'JARVIS_CODING_MODEL':'openai/gpt-6-sol','JARVIS_CODING_EFFORT':'high',
             'JARVIS_MASTER_MODEL':'','JARVIS_WORKER_MODEL':'','JARVIS_REVIEW_MODEL':''}
        process=subprocess.run([str(ROOT/'dist/Jarvis/Jarvis.exe'),'--internal','coding','run',ident],cwd=base,env=env,capture_output=True,timeout=240)
        state=json.loads((data/'coding-jobs'/ident/'status.json').read_text(encoding='utf-8'))
        report={'exit_code':process.returncode,'status':state['status'],'workers':len(state.get('workers',[])),
                'checks_passed':bool(state.get('checks')) and all(c['exit_code']==0 for c in state['checks']),
                'review_approved':state.get('review',{}).get('approved'),'budget':state.get('budget'),
                'original_unchanged':git(project,'rev-parse','HEAD')==before and not git(project,'status','--porcelain')}
        if state.get('error'):report['error']=state['error']
        (USER_DIR/'benchmarks/stage11-frozen-coding-smoke.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))
        if process.returncode:raise RuntimeError('Frozen coding acceptance failed')

if __name__=='__main__':main()
