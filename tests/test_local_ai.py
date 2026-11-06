import json
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from jarvis.assistant import Assistant
from jarvis.config import Settings
from jarvis.http import ServiceError
from jarvis.local_ai import ModelProcess,LocalText,own_process,worker_environment
from jarvis.ipc import JsonProcessClient
from jarvis.private_chat import PrivateChat
from jarvis.privacy import PrivateText
from jarvis.services import LocalServices
from jarvis.speech import Speaker
from jarvis.style_profile import StyleStore
from jarvis.tools import ToolRegistry


class LocalCommandTests(unittest.TestCase):
    def test_no_punctuation_and_platform_before_or_after_name_copy_message(self):
        for command in ('Напиши Пете в ВК сообщение Привет, буду в пять',
                        'Напиши в ВК Пете сообщение Привет, буду в пять'):
            with self.subTest(command=command):
                d=PrivateChat().handle(command,{})
                self.assertEqual(d.tool,'send_message')
                self.assertEqual(d.arguments,{'platform':'vk','recipient':'Пете','text':'Привет, буду в пять'})
                self.assertTrue(d.can_send)

    def test_missing_platform_is_asked_and_does_not_forget_dictation(self):
        p=PrivateChat();d=p.handle('Напиши Пете сообщение Привет!',{})
        self.assertIn('VK или Telegram',d.say);self.assertFalse(d.tool)
        d=p.handle('ВК',{})
        self.assertEqual(d.arguments,{'platform':'vk','recipient':'Пете','text':'Привет!'})
        self.assertTrue(d.can_send);self.assertIsNone(p.pending)

    def test_person_name_prefix_is_not_mistaken_for_technical_task(self):
        from jarvis.privacy import chat_action
        for name in ('Тестовому Контакту','Модулову','Программову'):
            self.assertTrue(chat_action('Напиши '+name+' сообщение привет'))
        self.assertFalse(chat_action('Напиши тесты для функции'))

    def test_missing_text_is_asked_instead_of_silently_opening_chat(self):
        p=PrivateChat();d=p.handle('Напиши Пете в ВК',{})
        self.assertIn('Какой текст',d.say);self.assertFalse(d.tool)
        d=p.handle('Привет, как дела?',{})
        self.assertEqual(d.tool,'send_message');self.assertEqual(d.arguments['text'],'Привет, как дела?')

    def test_model_proposal_needs_literal_data_and_confirmation(self):
        client=Mock();client.complete.return_value={'content':json.dumps({'action':'send','platform':'vk',
            'recipient':'Пете','text':'привет как дела'})}
        p=PrivateChat(client);d=p.handle('напиши Пете в вк привет как дела',{})
        self.assertIn('Отправить',d.say);self.assertFalse(d.tool)
        d=p.handle('да отправляй',{})
        self.assertEqual(d.tool,'send_message');self.assertTrue(d.can_send)
        client.complete.assert_called_once()
        client.complete.return_value={'content':json.dumps({'action':'send','platform':'vk',
            'recipient':'Пете','text':'ДОБАВЛЕННЫЙ МОДЕЛЬЮ ТЕКСТ'})}
        p=PrivateChat(client);d=p.handle('напиши Пете в вк привет как дела',{})
        self.assertFalse(d.tool);self.assertIn('Какой текст',d.say)

    def test_model_cannot_grant_sending_without_user_send_request(self):
        client=Mock();client.complete.return_value={'content':json.dumps({'action':'send','platform':'vk',
            'recipient':'Пете','text':'привет'})}
        d=PrivateChat(client).handle('прочитай Пете в вк привет',{})
        self.assertFalse(d.tool);self.assertIn('нужна ваша команда',d.say)

    def test_invalid_model_action_and_cancel_never_execute(self):
        client=Mock();client.complete.return_value={'content':'{"action":"execute_shell"}'}
        with self.assertRaises(ServiceError):PrivateChat(client).handle('напиши Пете в вк привет',{})
        p=PrivateChat();p.handle('Напиши Пете в ВК',{})
        d=p.handle('отмена',{});self.assertFalse(d.tool);self.assertIsNone(p.pending)

    def test_style_instruction_is_not_mistaken_for_literal_message_body(self):
        client=Mock();client.complete.return_value={'content':json.dumps({'action':'draft_style','platform':'vk',
            'recipient':'Пете','text':'Подготовь'})}
        d=PrivateChat(client).handle('Подготовь черновик Пете в ВК в моем стиле',{})
        self.assertEqual(d.tool,'draft_reply');self.assertFalse(d.can_send)

    def test_assistant_slot_filling_and_exit_have_zero_cloud_calls(self):
        registry=ToolRegistry(object(),LocalServices(Settings(),object()))
        registry.vk=Mock();registry.vk.send.return_value={'status':'sent','recipient_id':'1'}
        cloud=Mock();cloud.complete.side_effect=AssertionError('Cloud must not receive dictation')
        a=Assistant(registry,cloud)
        first=a.respond('Напиши Пете сообщение CANARY_PRIVATE')
        self.assertTrue(first.sensitive);registry.vk.send.assert_not_called()
        second=a.respond('ВК');self.assertTrue(second.sensitive)
        self.assertEqual(registry.vk.send.call_args.args,('Пете','CANARY_PRIVATE'))
        self.assertNotIn('CANARY_PRIVATE',json.dumps(a.history))
        local=Mock();registry.local_ai=local
        a.respond('Выход из приватного режима')
        self.assertFalse(a.private_session);self.assertIsNone(a.private_chat.pending)
        self.assertEqual(a.history,[]);local.close.assert_called_once();cloud.complete.assert_not_called()

    def test_new_confirmation_cannot_send_an_older_private_draft(self):
        registry=ToolRegistry(object(),LocalServices(Settings(),object()))
        registry.vk=Mock();registry.vk.send.return_value={'status':'sent','recipient_id':'2'}
        a=Assistant(registry,Mock());a.private_chat.client=Mock()
        a.private_chat.client.complete.return_value={'content':json.dumps({'action':'send','platform':'vk','recipient':'Новому','text':'привет'})}
        a.conversation.context={'dialog':{'platform':'vk','recipient':'1'},
            'private_draft':{'platform':'vk','recipient':'1','text':'OLDER_DRAFT'}}
        a.respond('Напиши Новому в ВК привет');registry.vk.send.assert_not_called()
        a.respond('Отправь')
        self.assertEqual(registry.vk.send.call_args.args,('Новому','привет'))

    def test_draft_is_private_and_can_be_sent_only_once(self):
        from jarvis.conversation import Conversation
        from jarvis.privacy import cloud_context
        c=Conversation();c.observe('draft_reply',{'platform':'vk','recipient':'1'},
            {'ok':True,'result':{'recipient':{'id':'1'},'text':'CANARY_DRAFT'}})
        self.assertNotIn('CANARY_DRAFT',json.dumps(cloud_context(c.context)))
        first=c.followup('Отправь');self.assertEqual(first[1]['text'],'CANARY_DRAFT')
        self.assertTrue(first[2]);self.assertIsNone(c.followup('Отправь'))


class LocalRuntimeTests(unittest.TestCase):
    def test_parent_exit_also_stops_child_created_after_job_assignment(self):
        base_python=str(Path(sys.base_prefix)/'python.exe')
        code=("import subprocess,sys; from jarvis.local_ai import own_process; "
              "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],creationflags=0x08000004); "
              "closer=own_process(p,resume=True); print(p.pid,flush=True); sys.stdin.read()")
        parent=subprocess.Popen([base_python,'-c',code],cwd=Path(__file__).resolve().parents[1],
                                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
                                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        api=ctypes.WinDLL('kernel32',use_last_error=True)
        api.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong];api.OpenProcess.restype=ctypes.c_void_p
        api.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
        api.TerminateProcess.argtypes=[ctypes.c_void_p,ctypes.c_uint];api.CloseHandle.argtypes=[ctypes.c_void_p]
        handle=None
        try:
            line=parent.stdout.readline();self.assertTrue(line.strip().isdigit())
            handle=api.OpenProcess(0x100001,False,int(line));self.assertTrue(handle)
            parent.kill();parent.wait(timeout=3)
            self.assertEqual(api.WaitForSingleObject(handle,3000),0)
        finally:
            if parent.poll() is None:parent.kill();parent.wait(timeout=3)
            if handle:api.TerminateProcess(handle,0);api.CloseHandle(handle)
            parent.stdin.close();parent.stdout.close();parent.stderr.close()

    def test_native_diagnostic_bytes_do_not_stop_stderr_reader(self):
        script="import sys,json; r=json.loads(sys.stdin.readline()); sys.stderr.buffer.write(b'\\xff\\nAFTER_BAD_BYTE\\n'); sys.stderr.flush(); print(json.dumps({'protocol_version':1,'id':r['id'],'ok':True,'result':{}}),flush=True)"
        client=JsonProcessClient([sys.executable,'-c',script])
        try:self.assertTrue(client.call('ping')['ok'])
        finally:client.close()
        self.assertIn('AFTER_BAD_BYTE',client._stderr)

    def test_local_configuration_loads_without_changing_privacy_defaults(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary);(folder/'local-ai.json').write_text(json.dumps({'enabled':True,'voice_enabled':True,'idle_seconds':45}))
            with patch('jarvis.config.USER_DIR',folder),patch.dict(os.environ,{'USERPROFILE':temporary},clear=True):
                s=Settings.load(root=folder)
            self.assertTrue(s.local_ai_enabled);self.assertTrue(s.local_voice_enabled)
            self.assertEqual(s.local_ai_idle_seconds,45);self.assertFalse(s.allow_cloud_asr)
            self.assertEqual(s.asr,'vosk')

    def test_idle_closes_only_owned_child_and_releases_process(self):
        owner=ModelProcess(idle_seconds=.03)
        child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],
                               creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            with owner.use():owner.process=child;owner.job_close=own_process(child)
            deadline=time.monotonic()+2
            while child.poll() is None and time.monotonic()<deadline:time.sleep(.02)
            self.assertIsNotNone(child.poll())
            self.assertFalse(owner.status()['running'])
        finally:owner.close()

    def test_worker_environment_is_offline_and_has_no_inherited_credentials(self):
        with patch.dict(os.environ,{'OPENROUTER_API_KEY':'CANARY','TELEGRAM_API_HASH':'CANARY','HF_TOKEN':'CANARY'}):
            env=worker_environment()
        self.assertNotIn('OPENROUTER_API_KEY',env);self.assertNotIn('HF_TOKEN',env)
        self.assertNotIn('TELEGRAM_API_HASH',env);self.assertEqual(env['HF_HUB_OFFLINE'],'1')

    def test_truncated_local_completion_fails_without_replay(self):
        local=LocalText({},idle_seconds=5)
        with patch.object(local,'start'),patch.object(local,'_request',return_value={
                'choices':[{'finish_reason':'length','message':{'content':'CANARY'}}]}) as transport:
            with self.assertRaises(ServiceError):local.complete([{'role':'user','content':'CANARY'}],[])
        transport.assert_called_once();local.close()

    def test_private_speech_uses_local_clone_without_windows_or_cloud(self):
        speaker=Speaker(Settings(local_voice_enabled=True))
        def synth(text,path,settings):Path(path).write_bytes(b'local WAV')
        speaker.local_ai=SimpleNamespace(voice=SimpleNamespace(synthesize=Mock(side_effect=synth)))
        with patch.object(speaker,'_play_file'),patch('jarvis.speech.windows_speak') as windows,patch('jarvis.cloud_voice.OpenRouterVoice.stream') as cloud:
            speaker.speak(PrivateText('CANARY_PRIVATE'))
        speaker.local_ai.voice.synthesize.assert_called_once();windows.assert_not_called();cloud.assert_not_called()

    def test_cached_private_reply_does_not_load_a_model_or_call_cloud(self):
        import wave
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'reply.wav'
            with wave.open(str(path),'wb') as f:
                f.setparams((1,2,16000,0,'NONE','not compressed'));f.writeframes(b'\0\0'*16000)
            speaker=Speaker(Settings(local_voice_enabled=True));speaker.local_ai=Mock()
            with patch('jarvis.local_voice_cache.cached_reply',return_value=path),patch.object(speaker,'_play_file') as play,patch('jarvis.speech.windows_speak') as windows:
                speaker.speak(PrivateText('Сообщение отправлено, сэр.'))
            play.assert_called_once();speaker.local_ai.voice.synthesize.assert_not_called();windows.assert_not_called()


class StyleTests(unittest.TestCase):
    def test_style_write_failure_does_not_hide_confirmed_message(self):
        registry=ToolRegistry(object(),LocalServices(Settings(),object()))
        registry.vk=Mock();registry.vk.send.return_value={'status':'sent','recipient_id':'1'}
        registry.style_store=Mock();registry.style_store.record.side_effect=OSError('disk unavailable')
        registry.can_send=True
        result=registry.send_message('vk','1','CANARY')
        self.assertEqual(result['status'],'sent');self.assertFalse(result['style_saved'])
        registry.vk.send.assert_called_once()

    def test_profile_uses_selected_outgoing_examples_and_owner_corrections_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            store=StyleStore(Path(temporary)/'style.json')
            count=store.learn('vk',{'recipient':{'id':'1'},'messages':[
                {'outgoing':True,'text':'ага, ща буду)'},{'outgoing':False,'text':'INCOMING_CANARY'}]})
            self.assertEqual(count,1);store.record('vk','1','не, давай завтра')
            data=store.context('vk','1');self.assertEqual(data['examples'],['ага, ща буду)','не, давай завтра'])
            self.assertNotIn('INCOMING_CANARY',store.path.read_text(encoding='utf-8'))
            self.assertEqual(store.context('telegram','1')['examples'],[])
            store.record('vk','2','OTHER_CONTACT');self.assertNotIn('OTHER_CONTACT',store.path.read_text(encoding='utf-8'))


if __name__=='__main__':unittest.main()
