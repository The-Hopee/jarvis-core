import json
import unittest
from unittest.mock import Mock

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
        for name in PRIVATE_TOOLS:
            with self.subTest(tool=name):
                result=registry.execute(name,{'platform':'vk','recipient':'PRIVATE','text':'CANARY'})
                self.assertFalse(result['ok']);self.assertEqual(result['error']['code'],'messaging_disabled')
        vk.send.assert_not_called();vk.read.assert_not_called();vk.open.assert_not_called()
        with self.assertRaises(ServiceError):registry.open_dialog('vk','PRIVATE')
        with self.assertRaises(ServiceError):registry.draft_reply('vk','PRIVATE')

    def test_disabled_dictation_stays_out_of_cloud_and_conversation_history(self):
        registry,vk=self.registry();cloud=Mock()
        assistant=Assistant(registry,cloud)
        for command in ('открой вк и напиши Пете CANARY_PRIVATE',
                        'Черкни Пете в телеграме CANARY_PRIVATE',
                        'Режим переписки','Запомни мой стиль в этом диалоге'):
            with self.subTest(command=command):
                turn=assistant.respond(command)
                self.assertIn('отключена',turn.text);self.assertTrue(turn.sensitive)
        self.assertNotIn('CANARY_PRIVATE',json.dumps(assistant.history))
        cloud.complete.assert_not_called();vk.send.assert_not_called()
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

    def test_public_questions_are_not_disabled_with_messaging(self):
        from jarvis.privacy import messaging_request
        for text in ('Скажи какая погода','Ответь на вопрос о физике',
                     'Давай что-нибудь от Егора Крида в ВК','Открой телеграм','Напиши код сортировки'):
            self.assertFalse(messaging_request(text),text)
        self.assertTrue(messaging_request('Скажи Пете в ВК CANARY_PRIVATE'))


if __name__=='__main__':unittest.main()
