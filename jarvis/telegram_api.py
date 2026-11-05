import asyncio
import getpass
from pathlib import Path
import re

from .config import ROOT, USER_DIR, read_env
from .http import ServiceError
from .messaging import MessageLedger, choose_recipient

SESSION = USER_DIR / 'telegram/user'


class TelegramAPI:
    def __init__(self, settings, ledger=None, *, cancelled=None):
        self.settings = settings
        self.ledger = ledger or MessageLedger()
        self.cancelled=cancelled or (lambda:False)

    def check_cancelled(self):
        if self.cancelled():
            from .jobs import JobCancelled
            raise JobCancelled('Задача отменена до отправки')

    def client(self):
        from telethon import TelegramClient
        if not self.settings.telegram_api_id or not self.settings.telegram_api_hash:
            raise ServiceError('Telegram API не подключён. Выполните python -m jarvis --telegram-login')
        if not SESSION.with_suffix('.session').is_file():
            raise ServiceError('Нужен вход в Telegram: python -m jarvis --telegram-login')
        return TelegramClient(str(SESSION), self.settings.telegram_api_id, self.settings.telegram_api_hash,
                              timeout=10, connection_retries=1, request_retries=0, auto_reconnect=False,
                              receive_updates=False, flood_sleep_threshold=0)

    def run(self, operation):
        async def execute():
            client = self.client()
            try:
                await client.connect()
                if not await client.is_user_authorized():
                    raise ServiceError('Сессия Telegram не авторизована. Повторите --telegram-login')
                self.check_cancelled()
                return await operation(client)
            finally:
                await client.disconnect()
        try:
            return asyncio.run(asyncio.wait_for(execute(), timeout=35))
        except ServiceError:
            raise
        except Exception as exc:
            from .jobs import JobCancelled
            if isinstance(exc,JobCancelled):raise
            raise ServiceError('Telegram API недоступен или отклонил запрос: ' + type(exc).__name__) from exc

    async def resolve(self, client, recipient):
        from telethon import utils, types
        candidates, entities = [], {}
        if recipient.startswith('@') and re.fullmatch(r'@[A-Za-z][A-Za-z0-9_]{3,31}', recipient):
            entity = await client.get_entity(recipient)
            if not isinstance(entity, types.User):
                raise ServiceError('Указанный адрес не является личным диалогом')
            item = {'id': str(utils.get_peer_id(entity)), 'name': utils.get_display_name(entity), 'username': entity.username or ''}
            return {'recipient': item, 'candidates': []}, entity
        async for dialog in client.iter_dialogs(limit=300):
            if not dialog.is_user:
                continue
            entity = dialog.entity
            item = {'id': str(dialog.id), 'name': dialog.name, 'username': getattr(entity, 'username', '') or ''}
            candidates.append(item)
            entities[item['id']] = entity
        selected = choose_recipient(recipient, candidates)
        return selected, entities.get(selected['recipient']['id']) if selected['recipient'] else None

    def find(self, recipient):
        async def operation(client):
            selected, _ = await self.resolve(client, recipient)
            return selected
        return self.run(operation)

    def open(self, recipient, kernel):
        async def operation(client):
            selected, entity = await self.resolve(client, recipient)
            if entity is None:
                return selected
            if entity.username:
                parameters = {'username': entity.username}
            elif entity.phone:
                parameters = {'phone': entity.phone.lstrip('+')}
            else:
                raise ServiceError('Диалог найден, но Telegram не предоставляет username или номер для открытия в Desktop')
            opened = kernel.call('open_telegram_dialog', parameters)['result']
            return {**selected, **opened}
        return self.run(operation)

    def read(self, recipient, limit=30):
        async def operation(client):
            selected, entity = await self.resolve(client, recipient)
            if entity is None:
                return selected
            messages = await client.get_messages(entity, limit=limit)
            return {**selected, 'messages': [
                {'id': message.id, 'text': (message.message or '')[:2000], 'outgoing': bool(message.out),
                 'time': message.date.isoformat(), 'has_attachment': bool(message.media)}
                for message in reversed(messages)], 'source': 'Telegram API'}
        return self.run(operation)

    def send(self, recipient, text, operation_id):
        async def operation(client):
            selected, entity = await self.resolve(client, recipient)
            if entity is None:
                return selected
            target = selected['recipient']
            self.check_cancelled()
            key, previous = self.ledger.begin(operation_id, 'telegram', target['id'])
            if previous:
                return {**previous, 'reused_receipt': True}
            try:
                message = await client.send_message(entity, text, parse_mode=None, link_preview=False)
                result = {'status': 'sent', 'recipient_id': target['id'], 'recipient_name': target['name'],
                          'message_id': message.id, 'text': text}
                self.ledger.finish(key, result)
                return result
            except (Exception, asyncio.CancelledError):
                # A network timeout can happen after Telegram accepts a message.
                return {'status': 'submitted_unverified', 'recipient_id': target['id'], 'do_not_retry': True}
        return self.run(operation)


def login(settings):
    from telethon import TelegramClient
    api_id = settings.telegram_api_id or int(input('Telegram api_id (my.telegram.org): ').strip())
    api_hash = settings.telegram_api_hash or getpass.getpass('Telegram api_hash (скрытый ввод): ').strip()
    if not api_id or not re.fullmatch('[a-fA-F0-9]{32}', api_hash):
        raise RuntimeError('Проверьте api_id и api_hash из my.telegram.org')
    SESSION.parent.mkdir(parents=True, exist_ok=True)
    async def authorize():
        client = TelegramClient(str(SESSION), api_id, api_hash, connection_retries=1)
        try:
            await client.start(phone=lambda: input('Номер телефона Telegram (+...): ').strip(),
                               code_callback=lambda: getpass.getpass('Код из Telegram (скрытый ввод): ').strip(),
                               password=lambda: getpass.getpass('Пароль двухэтапной защиты (скрытый ввод): '))
            me = await client.get_me()
            if me.bot:
                raise ServiceError('Нужен вход в пользовательский аккаунт, не bot token')
        finally:
            await client.disconnect()
    try:
        asyncio.run(authorize())
    except Exception as exc:
        raise RuntimeError('Вход в Telegram не завершён: ' + type(exc).__name__) from exc
    path = settings.root / '.env'
    original = path.read_text(encoding='utf-8-sig') if path.is_file() else ''
    for key, value in {'TELEGRAM_API_ID': str(api_id), 'TELEGRAM_API_HASH': api_hash}.items():
        pattern = rf'(?m)^\s*{key}\s*=.*$'
        if re.search(pattern, original):
            original = re.sub(pattern, lambda _m: key + '=' + value, original)
        else:
            original = original.rstrip('\n') + '\n' + key + '=' + value + '\n'
    path.write_text(original, encoding='utf-8')
    print('Telegram подключён. Сессия сохранена локально; сообщения при входе не отправлялись.')
