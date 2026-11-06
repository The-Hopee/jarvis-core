"""Real local LLM with fake accounts; publish metadata only, never account content."""
import json
from pathlib import Path
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from jarvis.assistant import Assistant
from jarvis.config import Settings,USER_DIR
from jarvis.local_ai import LocalAI
from jarvis.services import LocalServices
from jarvis.style_profile import StyleStore
from jarvis.tools import ToolRegistry


class FakeVK:
    def __init__(self):self.sent=[]
    def send(self,recipient,text,operation_id):
        self.sent.append((recipient,text));return {'status':'sent','recipient_id':'101'}
    def read(self,recipient,limit=30):
        return {'recipient':{'id':'101','name':'Тестовый Контакт'},'messages':[
            {'outgoing':True,'text':'ага, ща гляну)'},{'outgoing':False,'text':'Когда сможешь посмотреть?'}]}
    def open(self,recipient):return {'recipient':{'id':'101','name':'Тестовый Контакт'},'status':'opened'}
    def close(self):pass


def main():
    manifest=json.loads((USER_DIR/'local-model-install.json').read_text(encoding='utf-8'))
    local=LocalAI(manifest,90);cases=[]
    class CloudTrap:
        calls=0
        def complete(self,*a,**kw):self.calls+=1;raise AssertionError('Private request reached cloud')
    trap=CloudTrap()
    with tempfile.TemporaryDirectory() as temp:
        def assistant():
            r=ToolRegistry(object(),LocalServices(Settings(),object()));r.local_ai=local;r.vk=FakeVK()
            r.style_store=StyleStore(Path(temp)/'style.json')
            return Assistant(r,trap),r
        try:
            commands=[
                ('word_order','Напиши в ВК Тестовому Контакту сообщение Привет, буду через десять минут','send_message'),
                ('no_punctuation','Напиши Тестовому Контакту в ВК привет как дела','send_message'),
                ('open','Открой вконтакте диалог с Тестовым Контактом','open_dialog'),
                ('draft_style','Подготовь черновик ответа Тестовому Контакту в ВК в моем стиле','draft_reply'),
                ('literal_negation','Напиши Тестовому Контакту в ВК сообщение Не отправляй файлы.','send_message')]
            for ident,text,expected in commands:
                a,r=assistant();start=time.monotonic();turn=a.respond(text)
                confirmation=bool(a.private_chat.stage=='confirm')
                if confirmation:turn=a.respond('да отправляй')
                passed=any(t['name']==expected and t['output'].get('ok') for t in turn.tools)
                cases.append({'id':ident,'passed':passed,'seconds':round(time.monotonic()-start,3),'confirmation':confirmation,
                              'private':turn.sensitive,'cloud_calls':trap.calls})
                # Only synthetic diagnostic text; do not persist model answers.
                if not passed:print(json.dumps({'failed':ident,'synthetic_response':str(turn.text)},ensure_ascii=True),flush=True)
                print(json.dumps(cases[-1]),flush=True)
            a,r=assistant();first=a.respond('Напиши Тестовому Контакту сообщение Привет!');second=a.respond('ВК')
            cases.append({'id':'missing_platform','passed':not first.tools and bool(r.vk.sent) and second.sensitive})
            a.respond('Запомни мой стиль в этом диалоге')
            cases.append({'id':'style_saved_locally','passed':bool(r.style_store.context('vk','101')['examples'])})
            before=local.status();a.respond('Выход из приватного режима');after=local.status()
            report={'cases':cases,'cloud_calls':trap.calls,'before_exit':before,'after_exit':after,
                    'history_cleared':not a.history,'passed':all(c['passed'] for c in cases) and trap.calls==0 and not any(x['running'] for x in after.values())}
            directory=USER_DIR/'benchmarks';directory.mkdir(parents=True,exist_ok=True)
            (directory/'local-ai-real-smoke.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            print(json.dumps(report),flush=True)
            return 0 if report['passed'] else 1
        finally:local.close()


if __name__=='__main__':raise SystemExit(main())
