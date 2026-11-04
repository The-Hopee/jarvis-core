import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis.assistant import describe_tool
from jarvis.chat_intents import chat_intent
from jarvis.config import Settings
from jarvis.messaging import MessageLedger, choose_recipient, draft_reply
from jarvis.services import LocalServices
from jarvis.tools import ToolRegistry


class MessagingTests(unittest.TestCase):
    def test_matching_never_guesses_between_same_names(self):
        candidates = [{'id': '1', 'name': 'Петя', 'username': 'peter_one'},
                      {'id': '2', 'name': 'Петя', 'username': 'peter_two'}]
        self.assertIsNone(choose_recipient('Петя', candidates)['recipient'])
        self.assertEqual(choose_recipient('@peter_two', candidates)['recipient']['id'], '2')
        self.assertEqual(choose_recipient('1', candidates)['recipient']['id'], '1')
        self.assertEqual(choose_recipient('Петей', [candidates[0]])['recipient']['id'], '1')

    def test_ledger_marks_attempt_before_send_and_does_not_store_message_text(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = MessageLedger(Path(directory) / 'messages.sqlite')
            key, previous = ledger.begin('turn-one', 'telegram', '1')
            self.assertIsNone(previous)
            self.assertEqual(ledger.begin('turn-one', 'telegram', '1')[1]['status'], 'submitted_unverified')
            ledger.finish(key, {'status': 'sent', 'message_id': 8, 'recipient_id': '1', 'text': 'private-message'})
            saved = ledger.lookup('turn-one', 'telegram', '1')
            self.assertEqual(saved['message_id'], 8)
            self.assertNotIn('text', saved)
            self.assertIsNone(ledger.begin('turn-two', 'telegram', '1')[1])

    def test_send_requires_a_current_explicit_user_command(self):
        class Kernel: pass
        class Backend:
            def __init__(self): self.sent = []
            def send(self, recipient, text, operation_id):
                self.sent.append((recipient, text))
                return {'status': 'sent', 'message_id': 10, 'text': text}
        kernel = Kernel()
        registry = ToolRegistry(kernel, LocalServices(Settings(), kernel))
        backend = Backend()
        registry.telegram = backend
        args = {'platform': 'telegram', 'recipient': 'Петя', 'text': 'Привет!'}
        for command in ('открой диалог с Петей в телеграмме', 'напиши черновик и не отправляй'):
            registry.begin_turn(command)
            self.assertFalse(registry.execute('send_message', args)['ok'])
        self.assertEqual(backend.sent, [])
        registry.begin_turn('напиши Пете в телеграмме: Привет!')
        self.assertTrue(registry.execute('send_message', args)['ok'])
        self.assertEqual(backend.sent, [('Петя', 'Привет!')])

    def test_spoken_chat_commands_extract_person_and_literal_text(self):
        self.assertEqual(chat_intent('открой вконтакте диалог с Петей'),
                         ('open_dialog', {'platform': 'vk', 'recipient': 'Петей'}))
        self.assertEqual(chat_intent('открой диалог с Петей в телеграмме и напиши ему: Привет, буду в пять'),
                         ('send_message', {'platform': 'telegram', 'recipient': 'Петей', 'text': 'Привет, буду в пять'}))
        self.assertEqual(chat_intent('открой диалог с Петей в телеграмме и ответь на свое усмотрение в моем стиле')[0], 'reply_in_my_style')

    def test_style_uses_only_requested_dialogue_and_never_sends_itself(self):
        class Client:
            def complete(self, messages, tools, **kwargs):
                payload = json.loads(messages[1]['content'])
                self_payload = payload['style_examples']
                assert self_payload == ['ага, ща буду)']
                assert tools == [] and kwargs['allow_tools'] is False
                return {'content': 'ага, скоро буду)'}
        draft = draft_reply(Client(), {'recipient': {'name': 'Петя'}, 'messages': [
            {'text': 'ага, ща буду)', 'outgoing': True}, {'text': 'Ты где?', 'outgoing': False}]})
        self.assertEqual(draft['text'], 'ага, скоро буду)')
        self.assertEqual(draft['style_examples_used'], 1)

    def test_uncertain_send_is_not_reported_as_sent(self):
        text = describe_tool('send_message', {'ok': True, 'result': {'status': 'submitted_unverified'}})
        self.assertIn('не отправляю', text)
        self.assertNotIn('Сообщение отправлено', text)


class VKFixtureTests(unittest.TestCase):
    def test_real_browser_dialog_read_send_and_no_duplicate(self):
        from playwright.sync_api import sync_playwright
        from jarvis.vk_worker import VKPage
        html = '''<html><body>
        <input id="im_dialogs_search" placeholder="Поиск">
        <a href="/im?sel=42" onclick="event.preventDefault(); history.replaceState({},'',this.href); document.querySelector('.im-page--title-main').textContent='Петя';">
          <span class="im-dialog--name">Петя</span></a>
        <div class="im-page--title-main">Выберите диалог</div>
        <div id="messages"><div class="im-mess im-mess_out" data-msgid="1"><span class="im-mess--text">Привет)</span></div>
          <div class="im-mess" data-msgid="2"><span class="im-mess--text">Как дела?</span></div></div>
        <div contenteditable="true" class="im_editable"></div>
        <button aria-label="Отправить" onclick="const editor=document.querySelector('.im_editable'); const row=document.createElement('div'); row.className='im-mess im-mess_out';row.dataset.msgid='3'; const text=document.createElement('span');text.className='im-mess--text';text.textContent=editor.textContent;row.append(text);document.querySelector('#messages').append(row);editor.textContent='';">Отправить</button>
        </body></html>'''
        with tempfile.TemporaryDirectory() as directory, sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.route('https://vk.com/**', lambda route: route.fulfill(content_type='text/html; charset=utf-8', body=html))
                page.goto('https://vk.com/im')
                vk = VKPage(page, MessageLedger(Path(directory) / 'messages.sqlite'))
                dialog = vk.read_dialog('Петя', limit=10)
                self.assertEqual(dialog['recipient']['name'], 'Петя')
                self.assertEqual(len(dialog['messages']), 2)
                sent = vk.send_message('Петя', 'Буду в пять!', 'fixture-turn')
                self.assertEqual(sent['status'], 'sent')
                repeated = vk.send_message('Петя', 'Другой текст', 'fixture-turn')
                self.assertTrue(repeated['reused_receipt'])
                self.assertEqual(len(vk.messages(10)), 3)
                self.assertEqual(page.locator('.im_editable').inner_text(), '')
            finally:
                browser.close()


if __name__ == '__main__':
    unittest.main()
