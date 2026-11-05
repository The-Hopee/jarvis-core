"""Run the frozen program with empty private data and a restricted system PATH."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from jarvis.config import ROOT,USER_DIR
from jarvis.distribution import install,verify

def main():
    result={}
    with tempfile.TemporaryDirectory(prefix='jarvis-package-') as temporary:
        base=Path(temporary);install_root=base/'Программы с пробелами'
        target=install(ROOT/'dist/Jarvis',root=install_root,create_shortcuts=False)
        env={k:v for k,v in os.environ.items() if not any(word in k.upper() for word in ('API_KEY','TELEGRAM_API','JARVIS_','PYTHONPATH','VIRTUAL_ENV','ELEVENLABS'))}
        env.update({'JARVIS_DATA_DIR':str(base/'Новый профиль'),'LOCALAPPDATA':str(base/'Local'),
                    'PATH':os.environ['SystemRoot']+'\\System32;'+os.environ['SystemRoot']})
        executable=target/'Jarvis.exe'
        for name,arguments in [('runtime',['--self-test']),('doctor',['--doctor']),('control',['--internal','control','status']),('ui',['--ui-smoke']),('privacy',['--privacy-check'])]:
            process=subprocess.run([str(executable),*arguments],cwd=base,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=90)
            if process.returncode:
                print(process.stderr[-3000:]);raise RuntimeError(name+' failed: '+process.stdout[-1000:])
            result[name]=json.loads(process.stdout)
        process=subprocess.run([str(executable),'--once','состояние машины','--mute'],cwd=base,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=60)
        result['offline_system_command']=process.returncode==0 and 'Traceback' not in process.stderr
        result['no_private_key']=not result['runtime']['private_key_present']
        result['no_personal_voice']=not result['runtime']['voice_reference_present']
        result['manifest_valid_after_execution']=bool(verify(target))
        result['restricted_path']=True;result['cyrillic_and_spaces']=True
        # Public report contains only pass/fail and versions, no account data/paths.
        public={key:result[key] for key in ('offline_system_command','no_private_key','no_personal_voice','manifest_valid_after_execution','restricted_path','cyrillic_and_spaces')}
        public['runtime']=result['runtime'];public['doctor_passed']=True;public['control_passed']=True
        public['ui']=result['ui']
        public['privacy']=result['privacy']
        (USER_DIR/'benchmarks').mkdir(parents=True,exist_ok=True)
        (USER_DIR/'benchmarks/stage11-package-smoke.json').write_text(json.dumps(public,indent=2),encoding='utf-8')
        print(json.dumps(public,indent=2))

if __name__=='__main__':main()
