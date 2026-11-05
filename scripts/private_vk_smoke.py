"""One own diagnostic note through protected VK IPC; cloud client is a failing trap."""
import json
from pathlib import Path
import sys
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from jarvis.assistant import Assistant
from jarvis.config import Settings,USER_DIR
from jarvis.ipc import KernelClient
from jarvis.setup import ensure_native_config
from jarvis.services import LocalServices
from jarvis.tools import ToolRegistry

def main():
    settings=Settings.load()
    class CloudTrap:
        calls=0
        def complete(self,*a,**k):self.calls+=1;raise AssertionError('Private command reached a cloud client')
    trap=CloudTrap();canary='Jarvis: проверка приватного пути. '+uuid.uuid4().hex[:8]
    with KernelClient(settings.executable,ensure_native_config(settings)) as kernel:
        registry=ToolRegistry(kernel,LocalServices(settings,kernel))
        try:
            assistant=Assistant(registry,trap)
            turn=assistant.respond('Напиши Избранное в ВК: '+canary)
            outputs=[t['output'] for t in turn.tools]
            report={'self_note_sent':any(o.get('ok') and o['result'].get('status')=='sent' for o in outputs),
                    'cloud_model_calls':trap.calls,'private_turn':turn.sensitive,
                    'history_contains_note':canary in json.dumps(assistant.history,ensure_ascii=False),
                    'dictation_mode':settings.asr}
            if not report['self_note_sent']:
                import re
                from jarvis.privacy import clean_text
                report['error']=re.sub(r'https?://\S+','[URL OMITTED]',clean_text(str(turn.text)))[:240]
            (USER_DIR/'benchmarks/stage11-private-vk-smoke.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            print(json.dumps(report,indent=2));assert report['self_note_sent'] and trap.calls==0 and turn.sensitive and not report['history_contains_note']
        finally:registry.close()

if __name__=='__main__':main()
