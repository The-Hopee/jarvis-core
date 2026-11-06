"""Real OpenRouter tool selection; synthetic executors, no audio/account actions."""
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from jarvis.assistant import Assistant
from jarvis.budget import Budget
from jarvis.config import Settings,USER_DIR
from jarvis.routing import Router,make_client
from jarvis.services import LocalServices
from jarvis.tools import ToolRegistry


class FakeKernel:
    def call(self,method,params=None):
        if method=='list_apps':return {'result':{'applications':[
            {'app_id':'vscode','name':'Visual Studio Code','available':True},
            {'app_id':'notepad','name':'Блокнот','available':True}]}}
        return {'result':{'status':'shell_accepted','app_id':(params or {}).get('app_id','vscode')}}


class FakeVK:
    def search_music(self,query,limit=5):return {'query':query,'tracks':[{'artist':'Егор Крид','title':'Тестовый трек'}]}
    def play_music(self,query,index=1,operation_id=''):
        return {'query':query,'status':'playing','playback_verified':True,'track':{'artist':'Егор Крид','title':'Тестовый трек'}}
    def control_music(self,action,operation_id=''):
        return {'status':'paused' if action=='pause' else 'playing','pause_verified':action=='pause',
                'playback_verified':action!='pause','track':{'artist':'Егор Крид','title':'Тестовый трек'}}


def main():
    settings=replace(Settings.load(),messaging_enabled=False,local_ai_enabled=False,local_voice_enabled=False)
    budget=Budget(limit=.10)
    rows=[]
    cases=[
        ('music_free','Хочу послушать Егора Крида, включи что-нибудь из него','play_vk_music',None),
        ('music_vk','Вруби в ВК трек Егора Крида Будильник','play_vk_music',None),
        ('music_conversational','Давай что-нибудь от Егора Крида','play_vk_music',None),
        ('pause','Притормози музыку на минутку','control_vk_music','pause'),
        ('previous','А теперь верни предыдущую песню','control_vk_music','previous'),
        ('app','Будь добр, запусти редактор кода','open_application',None),
        ('video','Хочу посмотреть видео с Егором Кридом на ютубе, открой его','open_youtube_video',None),
        ('explanation','Как включить музыку во ВКонтакте?','no_action',None),
    ]
    with tempfile.TemporaryDirectory() as directory:
        router=Router(settings,path=Path(directory)/'mode.json')
        router.client=lambda route:make_client(settings.api_key,route.model,effort=route.effort,
            max_tokens=600,budget=budget,settings=settings)
        kernel=FakeKernel()
        for ident,text,expected,control in cases:
            registry=ToolRegistry(kernel,LocalServices(settings,kernel),shared_vk=FakeVK())
            registry.tools['open_youtube_video'].handler=lambda query,index=1:{'query':query,'title':'Тестовое видео','video_id':'test1234567'}
            # App results are synthetic; no actual application is launched.
            registry.tools['open_application'].handler=lambda app_id:{'app_id':app_id,'status':'shell_accepted'}
            calls=[];execute=registry.execute
            def capture(name,args):
                calls.append((name,args));return execute(name,args)
            registry.execute=capture
            assistant=Assistant(registry,router=router)
            if control:
                assistant.conversation.context={'last_media':'vk_music','vk_music_query':'Егор Крид',
                    'vk_music_track':{'artist':'Егор Крид','title':'Тестовый трек'},'vk_music_playing':True}
            start=time.monotonic()
            try:
                turn=assistant.respond(text)
                matched=[args for name,args in calls if name==expected]
                passed=bool(matched) and not turn.warning
                if control:passed=passed and matched[0].get('action')==control
                if expected=='play_vk_music':passed=passed and 'крид' in matched[0].get('query','').casefold()
                if expected=='no_action':passed=not calls and not turn.warning
                rows.append({'id':ident,'passed':passed,'seconds':round(time.monotonic()-start,3),
                    'selected_tools':[name for name,_ in calls],'warning':bool(turn.warning)})
            except Exception as exc:rows.append({'id':ident,'passed':False,'error':type(exc).__name__})
            finally:registry.close()
            print(json.dumps(rows[-1]),flush=True)
    report={'model':settings.model,'executor':'synthetic','real_account_actions':False,
            'microphone_tested':False,'cases':rows,'budget':budget.snapshot(),'passed':all(row['passed'] for row in rows)}
    target=USER_DIR/'benchmarks/cloud-command-smoke.json'
    target.write_text(json.dumps(report,ensure_ascii=True,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
