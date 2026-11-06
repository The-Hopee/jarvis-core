import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from jarvis.assistant import Assistant
from jarvis.config import Settings
from jarvis.http import ServiceError
from jarvis.privacy import PRIVATE_TOOLS
from jarvis.routing import Router
from jarvis.services import LocalServices
from jarvis.tools import ToolRegistry


class DisabledMessagingTests(unittest.TestCase):
    def registry(self):
        settings=Settings(messaging_enabled=False,local_ai_enabled=False,local_voice_enabled=False)
        kernel=Mock();vk=Mock()
        registry=ToolRegistry(kernel,LocalServices(settings,kernel),shared_vk=vk)
        self.addCleanup(registry.close)
        return registry,vk

    def test_private_tools_are_hidden_and_cannot_execute_even_with_send_grant(self):
        registry,vk=self.registry();registry.can_send=True
        names={d['function']['name'] for d in registry.definitions()}
        self.assertFalse(names & PRIVATE_TOOLS);self.assertIn('play_vk_music',names)
        self.assertFalse(set(registry.tools) & PRIVATE_TOOLS);self.assertIsNone(registry.telegram)
        for name in PRIVATE_TOOLS:
            with self.subTest(tool=name):
                result=registry.execute(name,{'platform':'vk','recipient':'PRIVATE','text':'CANARY'})
                self.assertFalse(result['ok']);self.assertEqual(result['error']['code'],'messaging_disabled')
        vk.send.assert_not_called();vk.read.assert_not_called();vk.open.assert_not_called()
        with self.assertRaises(ServiceError):registry.open_dialog('vk','PRIVATE')
        with self.assertRaises(ServiceError):registry.draft_reply('vk','PRIVATE')

    def test_disabled_messaging_does_not_filter_incoming_phrases(self):
        registry,vk=self.registry();cloud=Mock()
        cloud.complete.return_value={'content':'Ответ модели.'}
        assistant=Assistant(registry,cloud)
        for command in ('Включи в ВК песню Напиши мне',
                        'Открой OnlyOffice и напиши какой-нибудь текст',
                        'Напиши в документе сообщение о встрече',
                        'Режим переписки','Запомни мой стиль в этом диалоге'):
            with self.subTest(command=command):
                with patch('jarvis.privacy.chat_action',side_effect=AssertionError('Disabled filter was called')):
                    turn=assistant.respond(command)
                self.assertEqual(turn.text,'Ответ модели.')
                self.assertEqual(cloud.complete.call_args.args[0][-1]['content'],command)
        self.assertEqual(cloud.complete.call_count,5);vk.send.assert_not_called()
        self.assertIsNone(registry.local_ai)

    def test_free_form_music_reaches_cloud_tools_with_messaging_disabled(self):
        registry,vk=self.registry()
        vk.play_music.return_value={'status':'playing','playback_verified':True,
            'track':{'artist':'Егор Крид','title':'Тест'}}
        cloud=Mock();cloud.complete.side_effect=[{'content':None,'tool_calls':[{
            'id':'music1','type':'function','function':{'name':'play_vk_music',
                'arguments':json.dumps({'query':'Егор Крид'})}}]}, {'content':'Включаю трек.'}]
        turn=Assistant(registry,cloud).respond('Хочу послушать Егора Крида, давай его в ВК')
        self.assertEqual(vk.play_music.call_args.args,('Егор Крид',1))
        self.assertTrue(turn.tools[0]['output']['result']['playback_verified'])
        definitions=cloud.complete.call_args_list[0].args[1]
        self.assertFalse({d['function']['name'] for d in definitions} & PRIVATE_TOOLS)

    def test_home_tools_are_available_without_matching_a_music_phrase(self):
        router=Router(Settings(messaging_enabled=False),mode='auto')
        for command in ('Хочу послушать Егора Крида','Давай что-нибудь бодрое','Притормози это на минутку'):
            self.assertIn('play_vk_music',router.tools(router.route(command)))
            self.assertIn('control_vk_music',router.tools(router.route(command)))

    def test_document_text_cannot_route_into_disabled_messaging_skill(self):
        router=Router(Settings(messaging_enabled=False),mode='auto')
        route=router.route('Открой OnlyOffice и напиши текст: напиши Ивану в ВК сообщение о встрече')
        self.assertEqual(route.profile,'documents');self.assertNotIn('messaging',route.skills)
        self.assertIn('create_document',router.tools(route))

    def test_onlyoffice_compound_command_creates_real_docx(self):
        from jarvis.documents import Documents
        registry,_=self.registry()
        with tempfile.TemporaryDirectory() as directory:
            settings=Settings(messaging_enabled=False,document_roots=(Path(directory),))
            registry.documents=Documents(settings,registry.kernel)
            cloud=Mock();cloud.complete.side_effect=[{'content':None,'tool_calls':[{
                'id':'doc1','type':'function','function':{'name':'create_document','arguments':json.dumps({
                    'text':'Проверка документа. Сообщение внутри текста.',
                    'filename':'regression.docx','open_after':False})}}]}, {'content':'Документ создан.'}]
            turn=Assistant(registry,cloud).respond('Открой OnlyOffice и напиши текст: Проверка документа. Сообщение внутри текста.')
            result=turn.tools[0]['output'];self.assertTrue(result['ok'],result)
            saved=Path(result['result']['path']);self.assertTrue(saved.is_file())
            self.assertIn('Сообщение внутри текста.',registry.documents.read(str(saved))['text'])


if __name__=='__main__':unittest.main()
