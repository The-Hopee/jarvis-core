"""Serialized, visible VK messenger actions in a dedicated persistent browser."""
import argparse
import json
from pathlib import Path
import re
import sys
import time

from .http import ServiceError
from .messaging import MessageLedger, choose_recipient, normalized, name_key
from .vk_navigation import navigate

HEADERS=['.ConvoHeader__title','.im-page--title-main','.im-page--title','[data-testid="conversation-header-title"]','[class*="ConversationHeader"] [class*="Title"]']


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
        navigate(self.page, '/im', 'messenger', timeout=20)

    def open_dialog(self, recipient):
        self.ensure_messenger()
        self.self_dialog=False
        if normalized(recipient) in {'избранное','самому себе','себе','saved messages'}:
            search=self.first_visible(['[data-testid="me_convo_list"] input','input[placeholder="Поиск"]:not([data-testid="search_top_input"])'])
            if search is not None:
                search.click();search.fill('');self.page.wait_for_timeout(400)
            favorites=self.page.locator('.SearchConvoTab__importantUserName').filter(has_text=re.compile(r'^Избранное$'))
            choices=[favorites.nth(i) for i in range(favorites.count()) if favorites.nth(i).is_visible()]
            if len(choices)==1:
                choices[0].click();deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    header=self.first_visible(HEADERS)
                    if header is not None and normalized(header.inner_text())=='избранное':
                        self.self_dialog=True
                        return {'recipient':{'id':'self','name':'Избранное'},'status':'opened','url':self.page.url}
                    self.page.wait_for_timeout(100)
                raise ServiceError('Не удалось подтвердить Избранное VK; отправка не выполнялась')
        search = self.first_visible(['[data-testid="me_convo_list"] input[type="search"]', '.ConvoList__search input', '#im_dialogs_search', '.im-dialogs-search input',
            'input[placeholder*="диалог"]', 'input[placeholder*="Диалог"]',
            'input[placeholder="Поиск"]:not([data-testid="search_top_input"])', 'input[placeholder="Search"]', '[role="searchbox"]:not([data-testid="search_top_input"])'])
        if search is None:
            raise ServiceError('Не найден поиск диалогов VK. Откройте список сообщений в профиле Джарвиса.')
        search.fill(name_key(recipient))
        # Bounded wait for the messenger to update its local/server search results.
        self.page.wait_for_timeout(700)
        rows = self.page.locator('a[href*="sel="], a[href*="/im/convo/"], .im-dialog[data-peer], [data-testid="conversation-row"], [data-testid="vkme_convo_list_item"]')
        candidates, identities = [], set()
        for index in range(min(rows.count(), 100)):
            row = rows.nth(index)
            if not row.is_visible():
                continue
            heading = row.locator('.ConvoTitle,.im-dialog--name, [data-testid="conversation-title"], [class*="DialogName"], [class*="ConversationTitle"]')
            title = heading.first.inner_text().strip() if heading.count() else row.inner_text().strip().split('\n')[0]
            href = row.get_attribute('href') or ''
            peer = row.get_attribute('data-peer') or row.get_attribute('data-peer-id') or ''
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
        header = self.first_visible(HEADERS)
        if header is None or normalized(header.inner_text()) != normalized(target['name']):
            raise ServiceError('Не удалось однозначно подтвердить открытый диалог VK; сообщение не отправлено')
        return {'recipient': {'id': target['id'], 'name': target['name']}, 'status': 'opened', 'url': self.page.url}

    def messages(self, limit):
        rows = self.page.locator('.im-mess, [data-testid="message"], [data-message-id], .ConvoMessageWithoutBubble, .ConvoMessageBubble')
        result = []
        for index in range(max(0, rows.count() - limit), rows.count()):
            row = rows.nth(index)
            text_node = row.locator('.im-mess--text, [data-testid="message-text"], .MessageText')
            if not text_node.count():
                continue
            text = text_node.first.inner_text().strip()
            classes = row.get_attribute('class') or ''
            outgoing = bool(re.search(r'im-mess_out|is-out|outgoing|--outgoing', classes)) or row.get_attribute('data-outgoing') == 'true' or getattr(self,'self_dialog',False)
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
            '[data-testid="vkme_composer_input"][contenteditable="true"]',
            '[data-testid="message-input"][contenteditable="true"]',
            '[contenteditable="true"][data-placeholder*="сообщение"]',
            '[contenteditable="true"][role="textbox"]', 'textarea[placeholder*="сообщение"]'])
        send = self.first_visible(['button[aria-label="Отправить"]', 'button[aria-label="Send"]',
                                  '[data-testid="send-message"]', '.im-send-btn_send','[data-testid="vkme_composer_send"]'])
        if editor is None or send is None:
            raise ServiceError('Не найдены поле ввода и кнопка отправки VK; отправка не выполнялась')
        editor.fill(text)
        modern=editor.get_attribute('data-testid')=='vkme_composer_input'
        if modern:
            deadline=time.monotonic()+2
            while time.monotonic()<deadline and not re.match(r'Отправить|Send',send.get_attribute('aria-label') or '',re.I):self.page.wait_for_timeout(100)
            if not re.match(r'Отправить|Send',send.get_attribute('aria-label') or '',re.I):raise ServiceError('VK не переключил поле в режим отправки текста')
        if not send.is_enabled():
            raise ServiceError('Кнопка отправки VK недоступна; текст оставлен черновиком')
        header = self.first_visible(HEADERS)
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
                    if modern:
                        # A local optimistic bubble is insufficient: observe it again after reload.
                        self.page.reload(wait_until='domcontentloaded',timeout=20000)
                        persisted=False;deadline_reload=time.monotonic()+8
                        while time.monotonic()<deadline_reload:
                            header=self.first_visible(HEADERS)
                            seen=[m for m in self.messages(30) if m['outgoing'] and m['text']==text]
                            if header is not None and normalized(header.inner_text())==normalized(target['name']) and len(seen)>before:
                                persisted=True;break
                            self.page.wait_for_timeout(150)
                        if not persisted:break
                    result = {'status': 'sent', 'recipient_id': target['id'], 'recipient_name': target['name'],
                              'message_id': matching[-1]['id'], 'text': text}
                    self.ledger.finish(key, result)
                    return result
                self.page.wait_for_timeout(200)
        except Exception:
            pass
        return {'status': 'submitted_unverified', 'recipient_id': target['id'], 'do_not_retry': True}


class VKSession:
    """One profile and serialized IPC, separate pages for dialogs and playback."""
    def __init__(self, context):
        self.context, self.dialogs, self.music = context, None, None

    def new_page(self):
        for page in self.context.pages:
            if page.url == 'about:blank' and not (self.dialogs and page == self.dialogs.page) and not (self.music and page == self.music.page):
                return page
        return self.context.new_page()

    def dispatch(self, method, params):
        if method in {'open_dialog', 'read_dialog', 'send_message'}:
            if self.dialogs is None or self.dialogs.page.is_closed():
                self.dialogs = VKPage(self.new_page())
            return getattr(self.dialogs, method)(**params)
        if method in {'search_music', 'play_music', 'play_music_result', 'control_music'}:
            if method == 'control_music' and (self.music is None or self.music.page.is_closed()):
                return {'status': 'idle', 'playback_verified': False}
            if self.music is None or self.music.page.is_closed():
                from .vk_music import VKMusicPage
                self.music = VKMusicPage(self.new_page())
            handler = {'search_music': self.music.search, 'play_music': self.music.play,
                       'play_music_result': self.music.play_result, 'control_music': self.music.control}[method]
            return handler(**params)
        raise ServiceError('Неизвестный метод браузера')


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
            session = VKSession(context)
            for line in sys.stdin:
                request_id = None
                try:
                    if len(line.encode('utf-8')) > 1024 * 1024:
                        raise ServiceError('Запрос браузера слишком большой')
                    request = json.loads(line)
                    request_id = request.get('id')
                    result = session.dispatch(request.get('method'), request.get('params', {}))
                    response = {'protocol_version': 1, 'id': request_id, 'ok': True, 'result': result, 'error': None}
                except Exception as exc:
                    response = {'protocol_version': 1, 'id': request_id, 'ok': False, 'result': None,
                                'error': {'code': getattr(exc, 'code', 'browser_failed'), 'message': str(exc)[:700]}}
                print(json.dumps(response, ensure_ascii=False), flush=True)
        finally:
            context.close()


if __name__ == '__main__':
    main()
