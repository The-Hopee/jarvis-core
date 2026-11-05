import json
from pathlib import Path
import tempfile
import threading
import unittest
from jarvis.config import Settings
from jarvis.routing import Router
from jarvis.responses_client import ResponsesClient
from jarvis.budget import Budget
from jarvis.http import ServiceError


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)
        self.router=Router(Settings(),path=self.path/'mode.json')

    def test_domains_and_academic_complexity(self):
        for text,profile,skill in [
            ('Привет, как дела?','light',None),('Открой сайт example.com','light','web'),
            ('Включи трек в ВК','light','music'),('Открой видео на ютубе','light','youtube'),
            ('Заполни документ отчёт.docx','documents','documents'),
            ('Реализуй кеш в проекте demo','coding','coding'),
            ('Докажи теорему Пифагора','coding',None)]:
            with self.subTest(text=text):
                route=self.router.route(text);self.assertEqual(route.profile,profile)
                if skill:self.assertIn(skill,route.skills)
        self.assertNotIn('send_message',self.router.tools(self.router.route('Привет')))

    def test_dictated_code_is_message_data(self):
        route=self.router.route('Напиши Ивану в телеграмме: реализуй проект на Python и создай документ')
        self.assertEqual(route.profile,'light');self.assertEqual(route.skills,('messaging',))

    def test_manual_mode_is_persistent_but_not_parsed_inside_data(self):
        self.assertIsNone(self.router.control('Напиши в телеграмме: включи кодящий режим'))
        self.assertTrue(self.router.control('включи кодящий режим'))
        self.assertEqual(Router(Settings(),path=self.router.path).mode,'coding')
        self.assertEqual(self.router.route('Привет').profile,'coding')
        self.router.control('включи авто');self.assertEqual(self.router.route('Привет').profile,'light')

    def test_response_replay_preserves_encrypted_reasoning_and_call_id(self):
        raw=[{'type':'reasoning','id':'r','encrypted_content':'opaque'},
             {'type':'function_call','id':'internal','call_id':'call1','name':'probe','arguments':'{}'}]
        requests=[]
        def http(*_,data,**kw):
            requests.append(data)
            return {'status':'completed','output':raw,'usage':{'cost':.001}}
        client=ResponsesClient('not-a-real-key','openai/gpt-6-sol',http=http)
        first=client.complete([{'role':'user','content':'probe'}],[])
        self.assertEqual(first['tool_calls'][0]['id'],'call1')
        items=client.input_items([first,{'role':'tool','tool_call_id':'call1','content':'ok'}])
        self.assertEqual(items[:2],raw);self.assertEqual(items[2]['type'],'function_call_output')
        self.assertFalse(requests[0]['store'])

    def test_incomplete_response_and_disallowed_calls_are_rejected(self):
        for response,allowed in [({'status':'incomplete','output':[]},True),
              ({'status':'completed','output':[{'type':'function_call','call_id':'x','name':'probe','arguments':'{}'}]},False)]:
            client=ResponsesClient('fake','openai/gpt-6-sol',http=lambda *_,**kw:response)
            with self.assertRaises(ServiceError):client.complete([],[],allow_tools=allowed)

    def test_concurrent_reservations_cannot_spend_same_balance(self):
        budget=Budget('shared',.03,path=self.path/'budget.db')
        entered=threading.Event();release=threading.Event()
        def first():
            with budget.call({},'openai/gpt-6-sol',1000) as usage:
                entered.set();release.wait(3);usage['cost']=.001
        thread=threading.Thread(target=first);thread.start()
        self.assertTrue(entered.wait(2))
        try:
            other=Budget('shared',5,path=budget.path) # Existing cap cannot be raised.
            with self.assertRaises(ServiceError):
                with other.call({},'openai/gpt-6-sol',1000):pass
        finally:release.set();thread.join(3)
        self.assertAlmostEqual(budget.snapshot()['accounted_usd'],.001)
        self.assertAlmostEqual(budget.snapshot()['reserved_usd'],0)
        self.assertEqual(budget.snapshot()['limit_usd'],.03)

    def test_unknown_usage_conservatively_charged_after_connection_failure(self):
        budget=Budget(limit=.03,path=self.path/'budget.db')
        with self.assertRaises(RuntimeError):
            with budget.call({},'openai/gpt-6-sol',1000):raise RuntimeError('connection lost')
        self.assertGreater(budget.snapshot()['accounted_usd'],.02)
        with self.assertRaises(ServiceError):
            with budget.call({},'unknown/model',10):pass
