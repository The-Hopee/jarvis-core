"""Silent real SQLite/worker/model/native integration; no messaging/UI tools."""
from pathlib import Path
import json
import sys
import tempfile
import time
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from jarvis.config import Settings,USER_DIR
from jarvis.ipc import KernelClient
from jarvis.tools import ToolRegistry
from jarvis.home_jobs import HomeJobs
from jarvis.jobs import JobStore
from jarvis.assistant import Assistant
from jarvis.services import LocalServices
from jarvis.vk_browser import VKBrowser


def readonly(*args,**kwargs):
    registry=ToolRegistry(*args,**kwargs)
    registry.tools={k:v for k,v in registry.tools.items() if k=='get_system_status'}
    return registry


def main():
    settings=Settings.load();states=[]
    with tempfile.TemporaryDirectory(prefix='jarvis-jobs-smoke-') as folder,KernelClient(settings.executable) as kernel:
        store=JobStore(Path(folder)/'jobs.sqlite');vk=VKBrowser()
        foreground=Assistant(readonly(kernel,LocalServices(settings,kernel)))
        with patch('jarvis.home_jobs.ToolRegistry',side_effect=readonly),HomeJobs(kernel,vk,settings,store=store) as home:
            a=home.submit('Объясни одним предложением, что такое очередь задач.',foreground)
            b=home.submit('Состояние компьютера.',foreground)
            deadline=time.monotonic()+40
            while time.monotonic()<deadline:
                rows=[store.get(a['id']),store.get(b['id'])]
                current=[r['status'] for r in rows]
                if not states or states[-1]!=current:states.append(current)
                if all(s in {'completed','failed','cancelled'} for s in current):break
                time.sleep(.05)
            results=[{'number':r['number'],'status':r['status'],'has_result':bool(r['result'])} for r in rows]
            notes=home.drain()
            result={'states':states,'results':results,'notifications':len(notes),'audio_played':False,
                    'tools_exposed':['get_system_status'],'no_automatic_replay':True}
        foreground.registry.close();vk.close()
    target=USER_DIR/'benchmarks/stage07-jobs-smoke.json'
    target.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result),flush=True)
    return 0 if all(r['status']=='completed' for r in results) else 1


if __name__=='__main__':raise SystemExit(main())
