"""Browser transport and one-time local login for VK's web messenger."""
import sys

from .config import ROOT, USER_DIR
from .ipc import JsonProcessClient, KernelError
from .http import ServiceError
from .vk_navigation import VKLoginRequired, confirm_login, navigate

PROFILE = USER_DIR / 'vk-browser'


class VKBrowser:
    def __init__(self):
        self.process = None

    def call(self, method, **params):
        if self.process is None:
            command = [sys.executable.replace('pythonw.exe', 'python.exe'), '-m', 'jarvis.vk_worker', '--profile', str(PROFILE)]
            self.process = JsonProcessClient(command, timeout=50, cwd=ROOT)
        try:
            return self.process.call(method, params)['result']
        except KernelError as exc:
            if exc.code == 'vk_login_required':
                # Release the profile so the documented --vk-login command can
                # actually open it. Never hold an idle login window's lock.
                self.close()
            raise

    def open(self, recipient):
        return self.call('open_dialog', recipient=recipient)

    def read(self, recipient, limit=30):
        return self.call('read_dialog', recipient=recipient, limit=limit)

    def send(self, recipient, text, operation_id):
        return self.call('send_message', recipient=recipient, text=text, operation_id=operation_id)

    def search_music(self, query, limit=5):
        return self.call('search_music', query=query, limit=limit)

    def play_music(self, query, index=1, operation_id=''):
        return self.call('play_music', query=query, index=index, operation_id=operation_id)

    def play_music_result(self, index=1, operation_id=''):
        return self.call('play_music_result', index=index, operation_id=operation_id)

    def control_music(self, action, operation_id=''):
        if self.process is None:
            return {'status': 'idle', 'playback_verified': False}
        return self.call('control_music', action=action, operation_id=operation_id)

    def close(self):
        if self.process:
            self.process.close()
            self.process = None


def login():
    from playwright.sync_api import sync_playwright, Error as BrowserError
    PROFILE.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        try:
            context = playwright.chromium.launch_persistent_context(str(PROFILE), headless=False, locale='ru-RU')
        except BrowserError as exc:
            raise ServiceError('Не удалось открыть профиль VK. Остановите Джарвиса через manage.cmd stop и закройте его окно подключения VK, затем повторите --vk-login.') from exc
        try:
            page = context.pages[0] if context.pages else context.new_page()
            status = navigate(page, '/im', 'messenger', timeout=25, allow_login=True)
            if status == 'authenticated':
                print('Сохранённый вход в VK подтверждён. Повторная авторизация не нужна.')
                return
            print('Войдите в VK в открывшемся окне. Пароль вводите только на странице VK.')
            input('Дождитесь появления своей страницы VK, сообщений или музыки после входа и нажмите Enter здесь: ')
            confirm_login(context)
            print('Браузерный профиль сохранён локально. Сообщения при подключении не отправлялись.')
        except BrowserError as exc:
            raise ServiceError('Не удалось завершить проверку VK. Профиль сохранён; повторите --vk-login после загрузки страницы.') from exc
        finally:
            try:
                context.close()
            except BrowserError:
                pass
