"""Drive the real muted text CLI in an isolated user-data profile."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from jarvis.config import USER_DIR,ROOT


def main():
    with tempfile.TemporaryDirectory(prefix='jarvis-cli-jobs-') as folder:
        environment={**os.environ,'LOCALAPPDATA':folder,'PYTHONIOENCODING':'utf-8'}
        process=subprocess.Popen([sys.executable,'-m','jarvis','--text','--mute'],cwd=ROOT,env=environment,
                                 stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',
                                 creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            process.stdin.write('В фоне состояние компьютера\n');process.stdin.flush()
            time.sleep(2)
            process.stdin.write('Статус задач\nСостояние компьютера\n/exit\n');process.stdin.flush()
            out,err=process.communicate(timeout=30)
        finally:
            if process.poll() is None:process.kill();process.wait()
        result={'exit_code':process.returncode,'accepted':'принята в очередь' in out,
                'completion_notification':'Задача 1 готова' in out,'no_active_jobs':'Активных задач нет' in out,
                'traceback': 'Traceback' in err,'muted':True,'isolated_profile':True}
    target=USER_DIR/'benchmarks/stage07-cli-smoke.json'
    target.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result),flush=True)
    return 0 if result['exit_code']==0 and result['accepted'] and result['completion_notification'] and not result['traceback'] else 1


if __name__=='__main__':raise SystemExit(main())
