"""Serialized, visible VK messenger actions in a dedicated persistent browser."""
import argparse
import json
from pathlib import Path
import re
import sys
import time

from .http import ServiceError
from .messaging import MessageLedger, choose_recipient, normalized, name_key


class VKPage:
    def __init__(self, page, ledger=None):
        self.page, self.ledger = page, ledger or MessageLedger()

    def first_visible(self, selectors):
        for selector in selectors:
            items = self.page.locator(selector)
            for index in range(min(items.count(), 10)):
                item = items.nth(index)
                if item.is_visible():
                    return item
        return None

    def ensure_messenger(self):
        if not re.match(r'https://(?:[^/]+\.)?vk\.(?:com|ru)/(?:im|mail)', self.page.url):
            self.page.goto('https://vk.com/im', wait_until='domcontentloaded', timeout=25000)
        if not re.match(r'https://(?:[^/]+\.)?vk\.(?:com|ru)/(?:im|mail)', self.page.url) or self.first_visible([
            'input[type="password"]', 'input[name="login"]', 'input[name="phone"]']):
            raise ServiceError('Нужен вход в VK. Выполните python -m jarvis --vk-login')

    def open_dialog(self, recipient):
        self.ensure_messenger()
        search = self.first_visible(['#im_dialogs_search', '.im-dialogs-search input',
            'input[placeholder*="диалог"]', 'input[placeholder*="Диалог"]',
            'input[placeholder="Поиск"]', 'input[placeholder="Search"]', '[role="searchbox"]'])
        if search is None:
            raise ServiceError('Не найден поиск диалогов VK. Откройте список сообщений в профиле Джарвиса.')
        search.fill(name_key(recipient))
        # Bounded wait for the messenger to update its local/server search results.
        self.page.wait_for_timeout(700)
        rows = self.page.locator('a[href*="sel="], a[href*="/im/convo/"], .im-dialog[data-peer], [data-testid="conversation-row"]')
        candidates, identities = [], set()
        for index in range(min(rows.count(), 100)):
            row = rows.nth(index)
            if not row.is_visible():
                continue
            heading = row.locator('.im-dialog--name, [data-testid="conversation-title"], [class*="DialogName"], [class*="ConversationTitle"]')
            title = heading.first.inner_text().strip() if heading.count() else row.inner_text().strip().split('\n')[0]
            href = row.get_attribute('href') or ''
            peer = row.get_attribute('data-peer') or ''
            identity = href or peer
            if not title or not identity or identity in identities:
                continue
            identities.add(identity)
            candidates.append({'id': identity, 'name': title[:200], 'row_index': index})
        selected = choose_recipient(recipient, candidates)
        if not selected['recipient']:
            return selected
        target = selected['recipient']
        rows.nth(target['row_index']).click()
        self.page.wait_for_timeout(400)
        header = self.first_visible(['.im-page--title-main', '.im-page--title', '[data-testid="conversation-header-title"]',
                                     '[class*="ConversationHeader"] [class*="Title"]'])
        if header is None or normalized(header.inner_text()) != normalized(target['name']):
            raise ServiceError('Не удалось однозначно подтвердить открытый диалог VK; сообщение не отправлено')
        return {'recipient': {'id': target['id'], 'name': target['name']}, 'status': 'opened', 'url': self.page.url}

    def messages(self, limit):
        rows = self.page.locator('.im-mess, [data-testid="message"], [data-message-id]')
        result = []
        for index in range(max(0, rows.count() - limit), rows.count()):
            row = rows.nth(index)
            text_node = row.locator('.im-mess--text, [data-testid="message-text"], [class*="MessageText"]')
            if not text_node.count():
                continue
            text = text_node.first.inner_text().strip()
            classes = row.get_attribute('class') or ''
            outgoing = bool(re.search(r'im-mess_out|is-out|outgoing', classes)) or row.get_attribute('data-outgoing') == 'true'
            result.append({'id': row.get_attribute('data-msgid') or row.get_attribute('data-message-id'),
                           'text': text[:2000], 'outgoing': outgoing})
        return result

    def read_dialog(self, recipient, limit=30):
        opened = self.open_dialog(recipient)
        if not opened.get('recipient'):
            return opened
        return {**opened, 'messages': self.messages(limit), 'source': 'VK visible web dialog'}

    def send_message(self, recipient, text, operation_id):
        if not isinstance(text, str) or not 1 <= len(text) <= 4000:
            raise ServiceError('Сообщение должно содержать 1–4000 символов')
        opened = self.open_dialog(recipient)
        if not opened.get('recipient'):
            return opened
        target = opened['recipient']
        previous = self.ledger.lookup(operation_id, 'vk', target['id'])
        if previous:
            return {**previous, 'reused_receipt': True}
        editor = self.first_visible(['.im_editable[contenteditable="true"]',
            '[data-testid="message-input"][contenteditable="true"]',
            '[contenteditable="true"][data-placeholder*="сообщение"]',
            '[contenteditable="true"][role="textbox"]', 'textarea[placeholder*="сообщение"]'])
        send = self.first_visible(['button[aria-label="Отправить"]', 'button[aria-label="Send"]',
                                  '[data-testid="send-message"]', '.im-send-btn_send'])
        if editor is None or send is None:
            raise ServiceError('Не найдены поле ввода и кнопка отправки VK; отправка не выполнялась')
        editor.fill(text)
        if not send.is_enabled():
            raise ServiceError('Кнопка отправки VK недоступна; текст оставлен черновиком')
        header = self.first_visible(['.im-page--title-main', '.im-page--title', '[data-testid="conversation-header-title"]',
                                     '[class*="ConversationHeader"] [class*="Title"]'])
        if self.page.url != opened['url'] or header is None or normalized(header.inner_text()) != normalized(target['name']):
            raise ServiceError('Диалог изменился до отправки; сообщение не отправлено')
        key, previous = self.ledger.begin(operation_id, 'vk', target['id'])
        if previous:
            return {**previous, 'reused_receipt': True}
        before = len([m for m in self.messages(30) if m['outgoing'] and m['text'] == text])
        try:
            send.click(timeout=5000)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                matching = [m for m in self.messages(30) if m['outgoing'] and m['text'] == text]
                if len(matching) > before:
                    result = {'status': 'sent', 'recipient_id': target['id'], 'recipient_name': target['name'],
                              'message_id': matching[-1]['id'], 'text': text}
                    self.ledger.finish(key, result)
                    return result
                self.page.wait_for_timeout(200)
        except Exception:
            pass
        return {'status': 'submitted_unverified', 'recipient_id': target['id'], 'do_not_retry': True}


def main():
    from playwright.sync_api import sync_playwright
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', required=True)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    with sync_playwright() as playwright:
        profile = Path(args.profile)
        profile.mkdir(parents=True, exist_ok=True)
        context = playwright.chromium.launch_persistent_context(str(profile), headless=False, locale='ru-RU')
        try:
            page = context.pages[0] if context.pages else context.new_page()
            adapter = VKPage(page)
            methods = {'open_dialog': adapter.open_dialog, 'read_dialog': adapter.read_dialog, 'send_message': adapter.send_message}
            for line in sys.stdin:
                request_id = None
                try:
                    if len(line.encode('utf-8')) > 1024 * 1024:
                        raise ServiceError('Запрос браузера слишком большой')
                    request = json.loads(line)
                    request_id = request.get('id')
                    method = methods.get(request.get('method'))
                    if method is None:
                        raise ServiceError('Неизвестный метод браузера')
                    result = method(**request.get('params', {}))
                    response = {'protocol_version': 1, 'id': request_id, 'ok': True, 'result': result, 'error': None}
                except Exception as exc:
                    response = {'protocol_version': 1, 'id': request_id, 'ok': False, 'result': None,
                                'error': {'code': 'browser_failed', 'message': str(exc)[:700]}}
                print(json.dumps(response, ensure_ascii=False), flush=True)
        finally:
            context.close()


if __name__ == '__main__':
    main()
