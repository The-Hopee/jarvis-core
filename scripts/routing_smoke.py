"""Live Terra document tool test; no application launch, no messages, no audio."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import json
from jarvis.config import Settings,USER_DIR
from jarvis.routing import Router
from jarvis.assistant import Assistant
from jarvis.tools import ToolRegistry
from jarvis.services import LocalServices
from jarvis.ipc import KernelClient
from jarvis.setup import ensure_native_config

def main():
    settings=Settings.load();ensure_native_config(settings)
    with KernelClient(settings.executable) as kernel:
        registry=ToolRegistry(kernel,LocalServices(settings,kernel))
        try:
            assistant=Assistant(registry,router=Router(settings,mode='auto'))
            turn=assistant.respond('Создай документ с заголовком «Проверка Jarvis 0.8» и текстом «Тест профиля документов завершён». Не открывай файл после создания.')
            paths=[r['output'].get('result',{}).get('path') for r in turn.tools if r['output'].get('ok')]
            result={'profile':'documents','model':assistant.client.model,'tools':[{'name':r['name'],'ok':r['output'].get('ok')} for r in turn.tools],
                    'document_exists':any(p and Path(p).is_file() for p in paths),'warning':bool(turn.warning),
                    'budget':assistant.client.budget.snapshot()}
            output=USER_DIR/'benchmarks/stage08-routing-smoke.json';output.write_text(json.dumps(result,indent=2),encoding='utf-8')
            print(json.dumps(result,indent=2));assert result['document_exists'] and not turn.warning
        finally:registry.close()

if __name__=='__main__':main()
