"""Live paid master/worker/reviewer acceptance on a new isolated demonstration repo."""
import json
import os
from pathlib import Path
import sys
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from jarvis.config import USER_DIR
from jarvis.coding import git,atomic_json,PROJECTS,projects,job_directory,run_job,job_status

def main():
    root=USER_DIR/'demos'/('slugify-'+uuid.uuid4().hex[:8]);root.mkdir(parents=True)
    git(root,'init','-b','main')
    (root/'tests').mkdir()
    (root/'README.md').write_text('''# Slugify demonstration
Implement slugify(text: str) -> str in slugify.py. Lowercase, trim, replace runs of ASCII non-alphanumeric characters with one hyphen, strip edge hyphens. Empty input returns empty. No transliteration; non-ASCII characters are separators.
Examples: " Hello, WORLD! " -> "hello-world"; "a___b" -> "a-b"; "123" -> "123"; "!!!" -> "".
Tests must use Python unittest, cover all examples, repeated separators and empty strings. No external dependencies.
Split into exactly two independent tasks without dependencies: implementation owns slugify.py; tests own tests/test_slugify.py. Both workers implement against this specification. Integration runs all tests.
''',encoding='utf-8')
    (root/'slugify.py').write_text('def slugify(text: str) -> str:\n    raise NotImplementedError\n',encoding='utf-8')
    (root/'tests/test_slugify.py').write_text('import unittest\n',encoding='utf-8')
    (root/'.gitignore').write_text('__pycache__/\n',encoding='utf-8')
    git(root,'add','.');git(root,'commit','-m','Initial demo skeleton')
    before=git(root,'rev-parse','HEAD')
    data=projects();data['jarvis-demo']={'path':str(root),'checks':[[sys.executable,'-m','unittest','discover','-s','tests','-v']]};atomic_json(PROJECTS,data)
    ident=uuid.uuid4().hex[:24];directory=job_directory(ident)
    atomic_json(directory/'request.json',{'project_id':'jarvis-demo','goal':'Implement the complete README specification. Plan exactly two independent tasks: implementation (slugify.py) and tests (tests/test_slugify.py), no dependencies. Run configured tests and review the actual integrated diff.'})
    os.environ.update({name:'openai/gpt-6-sol' for name in ('JARVIS_MASTER_MODEL','JARVIS_WORKER_MODEL','JARVIS_REVIEW_MODEL')})
    print(json.dumps({'job_id':ident,'demo':str(root)}),flush=True)
    code=run_job(ident);state=job_status(ident)
    report={'job_id':ident,'status':state['status'],'workers':len(state.get('workers',[])),
            'checks_passed':bool(state.get('checks')) and all(c['exit_code']==0 for c in state['checks']),
            'review_approved':state.get('review',{}).get('approved'),
            'original_unchanged':git(root,'rev-parse','HEAD')==before and not git(root,'status','--porcelain'),
            'budget':state.get('budget'),'workspace':state.get('workspace'),'error':state.get('error')}
    (USER_DIR/'benchmarks/stage10-coding-smoke.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2));return code

if __name__=='__main__':raise SystemExit(main())
