"""Synthetic canary checks. Uses fake transports; never opens an account or network."""
import json
from unittest.mock import Mock,patch
from .config import Settings
from . import privacy

def main():
    from .assistant import Assistant
    from .services import LocalServices
    from .tools import ToolRegistry
    from .openrouter import OpenRouterClient
    from .cloud_voice import OpenRouterVoice
    from .http import request_json
    canary='SYNTHETIC_PRIVATE_CANARY_7c38b4'
    sent=[]
    def transport(*a,data,**k):sent.append(data);return {'choices':[{'message':{'content':'Готов.'}}]}
    client=OpenRouterClient('synthetic-test-key','synthetic-model',http=transport)
    backend=Mock();backend.send.return_value={'status':'sent','text':canary,'recipient':{'id':'self','name':'Canary'}}
    kernel=object();registry=ToolRegistry(kernel,LocalServices(Settings(),kernel));registry.telegram=backend
    assistant=Assistant(registry,client)
    turn=assistant.respond('Напиши Canary в телеграмме: '+canary)
    no_first_send=not sent
    assistant.respond('UNKNOWN_PRIVATE_DICTATION '+canary)
    session_guarded=not sent
    assistant.respond('Заверши переписку')
    assistant.respond('Привет')
    checks={'dictation_stayed_local':no_first_send,'private_turn_labelled':turn.sensitive,
            'private_session_blocks_unknown_dictation':session_guarded,
            'private_history_withheld':canary not in json.dumps(sent,ensure_ascii=False)}
    for name,action in [
        ('private_label_blocks_llm',lambda:client.complete([{'role':'user','content':privacy.PrivateText(canary)}],[])),
        ('cloud_asr_disabled',lambda:OpenRouterVoice(Settings(),http=transport).transcribe(b'\0\0'*100,16000)),
        ('private_tts_blocked',lambda:OpenRouterVoice(Settings()).speech_body(privacy.PrivateText(canary))),
        ('foreign_http_blocked',lambda:request_json('https://example.invalid/collect',data={'text':canary}))]:
        with patch('urllib.request.urlopen') as network:
            before=len(sent)
            try:action();checks[name]=False
            except privacy.PrivacyBlocked:checks[name]=len(sent)==before and not network.called
    registry.chat_model=client
    try:registry.draft_reply('vk','Canary');checks['cloud_style_disabled']=False
    except privacy.PrivacyBlocked:checks['cloud_style_disabled']=True
    registry.close()
    output={'passed':all(checks.values()),'checks':checks,'real_account_access':False,'real_network_requests':0}
    print(json.dumps(output,ensure_ascii=False,indent=2));return 0 if output['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
