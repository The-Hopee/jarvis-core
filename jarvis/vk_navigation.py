"""Bounded VK redirect handling and UI-only sign-in checks.

Login confirmation observes the user's completed login; it never submits an
authentication form or forces a second navigation through the OAuth callback.
"""
import time
from urllib.parse import urlsplit

from playwright.sync_api import Error as BrowserError
from .http import ServiceError

HOSTS = {'vk.com', 'vk.ru', 'www.vk.com', 'www.vk.ru', 'music.vk.com', 'music.vk.ru'}
AUTH_HOSTS = {'id.vk.com', 'id.vk.ru', 'login.vk.com', 'login.vk.ru', 'oauth.vk.com', 'oauth.vk.ru'}
FIELDS = {
    'profile': ['#top_profile_link', '.TopNavBtn__profileLink', '[data-testid="header-profile-menu-button"]',
                '[data-testid="header-profile-menu"]'],
    'messenger': ['#im_dialogs_search', '.im-dialogs-search', '[data-testid="me_convo_list"]',
                  '[data-testid="vkme_convo_list_item"]', '[data-testid="messenger"]',
                  '[data-testid="conversation-row"]'],
    'music': ['.audio_page', '.audio_page_layout', '.audio_row', '#audio_search',
              '[data-testid="MusicTrackRow"]', '[data-testid="search_audio_input"]',
              '[data-testid="audio-row"]', '[data-testid="track-row"]',
              'input[placeholder*="музык"]', 'input[placeholder*="аудиозапис"]',
              'input[placeholder*="Music"]'],
    'login': ['input[type="password"]', 'input[name="login"]', 'input[name="phone"]',
              'button[data-testid="login-button"]', '.VkIdForm', '#index_login'],
}


class VKLoginRequired(ServiceError):
    code = 'vk_login_required'


class VKNavigationError(ServiceError):
    code = 'vk_navigation_failed'


def state(page):
    if page.is_closed():
        raise VKNavigationError('Окно VK закрыто. Повторите команду подключения, чтобы открыть его снова.')
    try:
        # Read visibility/URL classification only, never names, chat text,
        # credentials, cookie values or OAuth query parameters.
        return page.evaluate("""fields => {
          const url = new URL(location.href);
          const visible = selectors => selectors.some(selector => Array.from(document.querySelectorAll(selector)).some(
            e => !!e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden'));
          return {host:url.hostname, path:url.pathname, protocol:url.protocol,
            ready:document.readyState !== 'loading', login:visible(fields.login),
            profile:visible(fields.profile), messenger:visible(fields.messenger), music:visible(fields.music)};
        }""", FIELDS)
    except BrowserError as exc:
        if page.is_closed():
            raise VKNavigationError('Окно VK закрыто. Подключение можно повторить.') from exc
        if any(marker in str(exc) for marker in ('Execution context was destroyed', 'Cannot find context', 'navigation', 'navigat')):
            return {'ready': False, 'host': '', 'path': '', 'protocol': ''}
        raise VKNavigationError('Не удалось проверить страницу VK. Сохранённый профиль не удалялся.') from exc


def classify(current, service=None):
    if current.get('protocol') != 'https:':
        return 'loading'
    host, path = current['host'], current['path']
    if host in AUTH_HOSTS or host in HOSTS and (path.startswith(('/login', '/auth')) or current.get('login')):
        return 'login'
    if host not in HOSTS:
        return 'external'
    if not current.get('ready'):
        return 'loading'
    messenger = path == '/im' or path.startswith('/im/') or path == '/mail' or path.startswith('/mail/')
    music = path.startswith('/audio') or host in {'music.vk.com', 'music.vk.ru'}
    if service == 'messenger':
        return 'authenticated' if messenger and current.get('messenger') else 'loading'
    if service == 'music':
        return 'authenticated' if music and current.get('music') else 'loading'
    return 'authenticated' if current.get('profile') or messenger and current.get('messenger') or music and current.get('music') else 'loading'


def wait_ready(page, service=None, timeout=10, allow_login=False):
    deadline = time.monotonic() + timeout
    while True:
        status = classify(state(page), service)
        if status == 'authenticated' or allow_login and status == 'login':
            return status
        if status == 'login' and not allow_login:
            raise VKLoginRequired('Нужен вход в VK в профиле Джарвиса: python -m jarvis --vk-login')
        if status == 'external':
            raise VKNavigationError('VK перенаправил на другой сайт. Дождитесь завершения входа в окне VK.')
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise VKNavigationError('Страница VK ещё не готова. Дождитесь загрузки; сохранённый профиль не удалялся.')
        try:
            page.wait_for_timeout(min(100, remaining * 1000))
        except BrowserError as exc:
            raise VKNavigationError('Окно VK закрыто до завершения перехода.') from exc


def navigate(page, path, service, *, timeout=20, allow_login=False, force=False):
    deadline = time.monotonic() + timeout
    current = state(page)
    if not force and classify(current, service) == 'authenticated':
        return 'authenticated'
    # Let an already-started VK callback settle before issuing any goto.
    if not force and current.get('host') in HOSTS and (current.get('path') in {'/index.php', '/al_im.php'} or
            service == 'messenger' and current.get('path', '').startswith(('/im', '/mail')) or
            service == 'music' and current.get('path', '').startswith('/audio')):
        try:
            return wait_ready(page, service, timeout=min(4, timeout), allow_login=allow_login)
        except VKNavigationError:
            if page.is_closed():
                raise
    host = current.get('host') if current.get('host') in {'vk.com', 'vk.ru', 'www.vk.com', 'www.vk.ru'} else 'vk.ru'
    target = 'https://' + host + path
    try:
        page.goto(target, wait_until='domcontentloaded', timeout=max(1, (deadline - time.monotonic()) * 1000))
    except BrowserError as exc:
        # A VK client-side redirect can abort goto after the HTTP response. Wait
        # for the destination instead of retrying the navigation or losing login.
        interrupted = 'interrupted by another navigation' in str(exc) or 'net::ERR_ABORTED' in str(exc)
        destination = urlsplit(page.url)
        if not interrupted or destination.hostname not in HOSTS | AUTH_HOSTS:
            raise VKNavigationError('Не удалось открыть страницу VK. Проверьте подключение; профиль сохранён.') from exc
    return wait_ready(page, service, timeout=max(0, deadline - time.monotonic()), allow_login=allow_login)


def confirm_login(context, timeout=20):
    """Observe all tabs after Enter; a successful account page is enough."""
    deadline = time.monotonic() + timeout
    while True:
        pages = [page for page in context.pages if not page.is_closed()]
        if not pages:
            raise VKNavigationError('Окно VK закрыто. Профиль сохранён; подключение можно повторить.')
        for page in pages:
            if classify(state(page)) == 'authenticated':
                return page
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise VKLoginRequired('Вход ещё не подтверждён. Повторите --vk-login и нажмите Enter после появления вашей страницы VK. Профиль не удалялся.')
        try:
            pages[0].wait_for_timeout(min(100, remaining * 1000))
        except BrowserError as exc:
            raise VKNavigationError('Окно VK закрыто до завершения проверки. Профиль сохранён.') from exc
