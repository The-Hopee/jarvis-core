"""Real GPU process/idle/network boundary checks, public synthetic speech only."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from jarvis.config import Settings,USER_DIR
from jarvis.local_ai import LocalAI


def gpu_memory():
    result=subprocess.run(['nvidia-smi','--query-gpu=memory.used','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=10)
    return int(result.stdout.strip().splitlines()[0]) if result.returncode==0 else None


def connections(pids):
    code='$owners=@('+','.join(str(int(p)) for p in pids)+'); '
    code+='$children=Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -in $owners }; '
    code+='$owners+=@($children.ProcessId); @((Get-NetTCPConnection -ErrorAction SilentlyContinue | Where-Object { $_.OwningProcess -in $owners }) | Select-Object LocalAddress,RemoteAddress,State) | ConvertTo-Json -Compress'
    result=subprocess.run(['powershell.exe','-NoLogo','-NoProfile','-NonInteractive','-Command',code],capture_output=True,text=True,timeout=20,
                          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:raise RuntimeError('Cannot inspect local model sockets')
    rows=json.loads(result.stdout) if result.stdout.strip() else []
    return rows if isinstance(rows,list) else [rows]


def main():
    manifest=json.loads((USER_DIR/'local-model-install.json').read_text(encoding='utf-8'));settings=Settings.load()
    models=LocalAI(manifest,90);baseline=gpu_memory()
    try:
        models.text.complete([{'role':'user','content':'Say only OK.'}],[])
        with tempfile.TemporaryDirectory(prefix='jarvis-local-lifecycle-') as temporary:
            models.voice.synthesize('Проверка завершена, сэр.',Path(temporary)/'public.wav',settings)
        before=models.status();during=gpu_memory();pids=[v['pid'] for v in before.values() if v['pid']]
        sockets=connections(pids)
        remote=[c for c in sockets if c['RemoteAddress'] not in {'127.0.0.1','::1','0.0.0.0','::'}]
        voice_probe=models.voice.client.call('privacy_probe')['result']['network_blocked']
        models.text.idle_seconds=1;models.voice.idle_seconds=1
        with models.text.use():pass
        with models.voice.use():pass
        deadline=time.monotonic()+8
        while any(v['running'] for v in models.status().values()) and time.monotonic()<deadline:time.sleep(.1)
        after=models.status();released=gpu_memory()
        report={'before_idle':before,'after_idle':after,'gpu_MiB':{'baseline':baseline,'loaded':during,'after_idle':released},
                'only_loopback_connections':not remote,'voice_network_blocked':voice_probe,
                'passed':all(v['running'] for v in before.values()) and not any(v['running'] for v in after.values()) and not remote and voice_probe}
        (USER_DIR/'benchmarks/local-lifecycle-real-smoke.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report),flush=True);return 0 if report['passed'] else 1
    finally:models.close()


if __name__=='__main__':raise SystemExit(main())
