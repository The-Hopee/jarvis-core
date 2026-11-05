"""VK music through visible controls, with observed HTML audio playback.

No stream URLs, account tokens, downloads or subscription actions are exposed.
Selectors cover classic VK and semantic track controls; signed-in live layouts
still need verification in the user's dedicated browser profile.
"""
import hashlib
import re
import time
from urllib.parse import urlencode, urlsplit

from .http import ServiceError
from .vk_browser import VKLoginRequired

ROWS = '.audio_row, [data-testid="audio-row"], [data-testid="track-row"], [data-test-id="track-row"]'
TITLES = ['.audio_row__title_inner', '.audio_row__title', '[data-testid="track-title"]', '[data-testid="audio-title"]', '[class*="AudioRow_title"]']
ARTISTS = ['.audio_row__performers', '.audio_row__performer', '[data-testid="track-artist"]', '[data-testid="audio-artist"]', '[class*="AudioRow_artist"]']
PLAY = ['.audio_row__play_btn', '.audio_row__play', '[data-testid="track-play"]', '[data-testid="audio-play"]',
        'button[aria-label*="Воспроизвести"]', 'button[aria-label*="Слушать"]', 'button[aria-label="Play"]']
PAUSE = ['[data-testid="track-pause"]', 'button[aria-label="Пауза"]', 'button[aria-label="Pause"]']
ACTIVE = '.audio_row__playing, .audio_row_playing, .audio_row--playing, [data-playing="true"], [aria-current="true"]'
DOM_FIELDS = {'titles': TITLES, 'artists': ARTISTS, 'buttons': PLAY + PAUSE, 'active': ACTIVE, 'pause': PAUSE}

# VK may use detached new Audio() elements. Observe them without changing play()
# semantics, autoplay restrictions, URLs, or event delivery. Keep only 16 objects.
TRACK_AUDIO = """() => {
  if (window.__jarvisMusicAudio) return;
  const known = new Set();
  known.playOrder = new WeakMap();
  known.sequence = 0;
  const watched = new WeakSet(), events = new WeakSet();
  const playing = event => {
    if (event.target.tagName !== 'AUDIO' || events.has(event)) return;
    events.add(event); known.add(event.target);
    known.playOrder.set(event.target, ++known.sequence);
    if (known.size > 16) known.delete(known.values().next().value);
  };
  Object.defineProperty(window, '__jarvisMusicAudio', {value: known});
  document.addEventListener('playing', playing, true);
  const original = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function(...args) {
    if (this.tagName === 'AUDIO') {
      known.add(this);
      if (!watched.has(this)) { this.addEventListener('playing', playing); watched.add(this); }
      if (known.size > 16) known.delete(known.values().next().value);
    }
    return Reflect.apply(original, this, args);
  };
}"""


def key(text):
    return ' '.join(re.findall(r'\w+', text.casefold().replace('ё', 'е')))


def visible(scope, selectors):
    for selector in selectors:
        items = scope.locator(selector)
        for index in range(min(items.count(), 10)):
            candidate = items.nth(index)
            if candidate.is_visible():
                return candidate
    return None


def label(scope, selectors):
    item = visible(scope, selectors)
    return ' '.join(item.inner_text().split())[:200] if item is not None else ''


class VKMusicPage:
    def __init__(self, page, timeout=6):
        self.page, self.timeout = page, timeout
        self.results, self.query, self.current = [], '', None
        self.receipts = {}
        self.verified_playback = None
        page.add_init_script('(' + TRACK_AUDIO + ')()')
        page.evaluate(TRACK_AUDIO)

    def ensure_music(self):
        url = urlsplit(self.page.url)
        if not (url.scheme == 'https' and (url.hostname in {'music.vk.com', 'music.vk.ru'} or
                url.hostname in {'vk.com', 'vk.ru', 'www.vk.com', 'www.vk.ru'} and url.path.startswith('/audio'))):
            self.page.goto('https://vk.com/audio', wait_until='domcontentloaded', timeout=20000)
        self.require_login()

    def require_login(self):
        url = urlsplit(self.page.url)
        route = (url.hostname in {'vk.com', 'vk.ru', 'www.vk.com', 'www.vk.ru'} and url.path.startswith('/audio') or
                 url.hostname in {'music.vk.com', 'music.vk.ru'} and not url.path.startswith(('/login', '/auth')))
        if url.scheme != 'https' or not route or visible(self.page, [
                'input[type="password"]', 'input[name="login"]', 'input[name="phone"]',
                'button[data-testid="login-button"]', '.VkIdForm', '#index_login']):
            raise VKLoginRequired('Нужен вход в VK в профиле Джарвиса: python -m jarvis --vk-login')

    def tracks(self):
        # One DOM snapshot, rather than thousands of IPC calls on long lists.
        rows = self.page.locator(ROWS).evaluate_all("""(rows, fields) => {
          const visible = el => !!el && !!el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden';
          const first = (row, selectors) => {
            for (const selector of selectors) for (const el of row.querySelectorAll(selector)) if (visible(el)) return el;
            return null;
          };
          const text = el => el ? el.innerText.replace(/\\s+/g, ' ').trim().slice(0, 200) : '';
          return rows.slice(0, 150).map((row, index) => {
            if (!visible(row) || row.dataset.ad === 'true' || row.dataset.sponsored === 'true' || !first(row, fields.buttons)) return null;
            const title = text(first(row, fields.titles));
            if (!title) return null;
            return {title, artist:text(first(row, fields.artists)),
              identity:row.getAttribute('data-full-id') || row.getAttribute('data-track-id') || '', _row:index,
              _playing:row.matches(fields.active) || fields.pause.some(s => !!row.querySelector(s))};
          }).filter(Boolean);
        }""", DOM_FIELDS)
        result, seen = [], set()
        for row in rows:
            title, artist, identity = row['title'], row['artist'], row.pop('identity')
            if not re.fullmatch(r'[\w:-]{1,100}', identity, re.ASCII):
                identity = 'text-' + hashlib.sha256((title + '\0' + artist).encode()).hexdigest()[:20]
            if identity in seen:
                continue
            seen.add(identity)
            result.append({'id': identity, **row})
        return result

    @staticmethod
    def public(track):
        return {k: track[k] for k in ('title', 'artist')}

    def now_track(self):
        selected = [t for t in self.tracks() if t['_playing']]
        if selected:
            return selected[0]
        player = visible(self.page, ['.audio_page_player', '.top_audio_player', '[data-testid="music-player"]'])
        if player is not None:
            title = label(player, ['.audio_page_player_title_song', '.top_audio_player_title', *TITLES])
            artist = label(player, ['.audio_page_player_title_performer', '.top_audio_player_performer', *ARTISTS])
            if title:
                return {'id': 'text-' + hashlib.sha256((title + '\0' + artist).encode()).hexdigest()[:20],
                        'title': title, 'artist': artist}
        return None

    def search(self, query, limit=5):
        query = query.strip()
        if not 1 <= len(query) <= 200 or not 1 <= limit <= 5:
            raise ServiceError('Укажите название/исполнителя до 200 символов и limit от 1 до 5')
        self.ensure_music()
        previous = [(t['id'], t['title'], t['artist']) for t in self.tracks()]
        old_query = self.query
        self.results, self.query = [], query
        search = visible(self.page, ['#audio_search input', 'input#audio_search', '.audio_page__search input',
            'input[placeholder*="музык"]', 'input[placeholder*="аудиозапис"]', 'input[placeholder*="трек"]',
            'input[placeholder*="Music"]', 'input[placeholder="Поиск"]', '[role="searchbox"]'])
        if search is not None:
            search.fill(query)
            search.press('Enter')
        else:
            # A fixed VK route with encoded data, never a model-provided URL.
            self.page.goto('https://vk.com/audio?' + urlencode({'act': 'search', 'q': query}),
                           wait_until='domcontentloaded', timeout=20000)
            previous = []
        deadline = time.monotonic() + self.timeout
        # Require a settled result change, the same query, or genuinely matching
        # existing rows. This avoids playing stale results during network delay.
        settled, signature = 0, None
        while time.monotonic() < deadline:
            self.require_login()
            found = self.tracks()
            current = [(t['id'], t['title'], t['artist']) for t in found]
            matching = any(all(word in key(t['title'] + ' ' + t['artist']) for word in key(query).split()) for t in found)
            if current == previous and old_query != query and matching:
                found = [t for t in found if all(word in key(t['title'] + ' ' + t['artist']) for word in key(query).split())]
                current = [(t['id'], t['title'], t['artist']) for t in found]
            fresh = current != previous or old_query == query or matching
            loading = visible(self.page, ['[data-testid="music-loading"]', '.audio_page__search [aria-busy="true"]'])
            if found and fresh and loading is None:
                settled = settled + 1 if current == signature else 0
                if settled >= 2:
                    self.results = found[:limit]
                    return {'query': query, 'tracks': [self.public(t) for t in self.results], 'source': 'VK browser'}
            signature = current
            self.page.wait_for_timeout(200)
        self.require_login()
        login = self.page.get_by_role('button', name=re.compile(r'^(?:Войти|Войти в аккаунт|Log in)$', re.I))
        if login.count() and login.first.is_visible():
            raise VKLoginRequired('Для музыки нужен вход в VK: python -m jarvis --vk-login')
        raise ServiceError('Треки VK не найдены или поиск не загрузился. Уточните название/исполнителя; если VK изменил интерфейс, нужны новые селекторы.')

    def audio(self):
        return self.page.evaluate("""() => {
          const elements = Array.from(new Set([...document.querySelectorAll('audio'), ...(window.__jarvisMusicAudio || [])]));
          return elements.map((a, i) => ({index:i, paused:a.paused, ended:a.ended,
            time:a.currentTime, duration:Number.isFinite(a.duration)?a.duration:null,
            ready:a.readyState, muted:a.muted, volume:a.volume,
            sequence:window.__jarvisMusicAudio?.playOrder?.get(a) || 0}));
        }""")

    def row(self, expected):
        rows = self.page.locator(ROWS)
        if expected['_row'] >= rows.count():
            raise ServiceError('Результаты VK изменились. Попросите найти трек заново.')
        row = rows.nth(expected['_row'])
        actual = next((t for t in self.tracks() if t['_row'] == expected['_row']), None)
        if actual is None or any(actual[k] != expected[k] for k in ('id', 'title', 'artist')):
            raise ServiceError('Порядок результатов VK изменился; другой трек не запускался. Повторите поиск.')
        return row

    def selected(self, row):
        return row.evaluate("(row, fields) => row.matches(fields.active) || fields.pause.some(s => !!row.querySelector(s))", DOM_FIELDS)

    def progressing(self, before, after_sequence=None):
        positions = {a['index']: a['time'] for a in before}
        return next((a for a in self.audio() if not a['paused'] and not a['ended'] and a['ready'] >= 2 and
                     (after_sequence is None or a['sequence'] > after_sequence) and
                     a['time'] > positions.get(a['index'], 0) + 0.05), None)

    def playback_result(self, track, index, playing, status):
        if playing is not None:
            self.verified_playback = (key(track['title']), key(track['artist']), playing['sequence'])
        return {'track': self.public(track), 'query': self.query, 'result_index': index, 'status': status,
                'playback_verified': playing is not None, 'do_not_retry': playing is None,
                'duration_seconds': playing['duration'] if playing else None}

    def once(self, operation_id, action, callback):
        cache_key = (operation_id, *action)
        if operation_id and cache_key in self.receipts:
            return {**self.receipts[cache_key], 'reused_receipt': True}
        result = callback()
        if operation_id:
            if len(self.receipts) >= 64:
                self.receipts.pop(next(iter(self.receipts)))
            self.receipts[cache_key] = result
        return result

    def play(self, query, index=1, operation_id=''):
        cached = self.receipts.get((operation_id, 'play', query.strip(), index)) if operation_id else None
        if cached:
            return {**cached, 'reused_receipt': True}
        self.search(query, limit=5)
        return self.play_result(index, operation_id)

    def play_result(self, index=1, operation_id=''):
        return self.once(operation_id, ('play', self.query, index), lambda: self._play_result(index))

    def _play_result(self, index):
        if not 1 <= index <= len(self.results):
            raise ServiceError('В предыдущем поиске VK нет трека с таким номером. Сначала попросите найти музыку.')
        self.require_login()
        track = self.results[index - 1]
        row = self.row(track)
        before = self.audio()
        active = self.selected(row)
        if active and any(not a['paused'] and not a['ended'] for a in before):
            self.current = track
            self.page.wait_for_timeout(200)
            playing = self.progressing(before)
            if playing and self.verified_playback != (key(track['title']), key(track['artist']), playing['sequence']):
                playing = None
            # Do not toggle a loading/playing track off by clicking again.
            return self.playback_result(track, index, playing, 'already_playing' if playing else 'play_requested')
        button = visible(row, PLAY)
        if button is None or not button.is_enabled():
            raise ServiceError('Кнопка воспроизведения выбранного трека VK недоступна')
        self.current = track
        sequence = max((a['sequence'] for a in before), default=0)
        button.click(timeout=4000)
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            self.page.wait_for_timeout(150)
            playing = self.progressing(before, after_sequence=sequence)
            if playing and self.selected(self.row(track)):
                return self.playback_result(track, index, playing, 'playing')
            before = self.audio()
        return self.playback_result(track, index, None, 'play_requested')

    def control(self, action, operation_id=''):
        return self.once(operation_id, ('control', action), lambda: self._control(action))

    def _control(self, action):
        if action not in {'pause', 'resume', 'next', 'previous', 'status'}:
            raise ServiceError('Неизвестная команда проигрывателя VK')
        self.require_login()
        before = self.audio()
        observed = self.now_track()
        if observed:
            self.current = observed
        if action == 'status':
            self.page.wait_for_timeout(150)
            playing = self.progressing(before)
            status = 'playing' if playing else 'paused' if before and all(a['paused'] or a['ended'] for a in before) else 'buffering' if before else 'idle'
            return {'status': status,
                    'playback_verified': playing is not None, 'track': self.public(track) if (track := self.now_track()) else None}
        if action == 'pause':
            if not before:
                return {'status': 'idle', 'playback_verified': False}
            # pause() is idempotent and dispatches the normal media event, even
            # for detached Audio objects. It does not toggle another track on.
            self.page.evaluate("""() => new Set([...document.querySelectorAll('audio'), ...(window.__jarvisMusicAudio || [])]).forEach(a => a.pause())""")
            paused = all(a['paused'] for a in self.audio())
            return {'status': 'paused' if paused else 'control_requested', 'pause_verified': paused, 'playback_verified': False}
        if action == 'resume' and before:
            if not any(not a['paused'] and not a['ended'] for a in before):
                button = visible(self.page, ['.audio_page_player_play', '.top_audio_player_play',
                    '[data-testid="player-play"]', '[data-testid="player-toggle"]'])
                if button is None and self.current and self.current.get('_row') is not None:
                    button = visible(self.row(self.current), PLAY)
                if button is None:
                    raise ServiceError('Не найдена кнопка продолжения музыки VK')
                button.click(timeout=4000)
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                self.page.wait_for_timeout(150)
                playing = self.progressing(before)
                if playing:
                    track = self.now_track()
                    if track:
                        self.verified_playback = (key(track['title']), key(track['artist']), playing['sequence'])
                    return {'status': 'playing', 'playback_verified': True,
                            'track': self.public(track) if track else None}
                before = self.audio()
            return {'status': 'play_requested', 'playback_verified': False, 'do_not_retry': True}
        if action in {'next', 'previous'} and self.current:
            sequence = max((a['sequence'] for a in before), default=0)
            selectors = ['.audio_page_player_next', '.top_audio_player_next', '[data-testid="player-next"]', 'button[aria-label="Следующий трек"]'] if action == 'next' else [
                '.audio_page_player_prev', '.top_audio_player_prev', '[data-testid="player-previous"]', 'button[aria-label="Предыдущий трек"]']
            button = visible(self.page, selectors)
            if button is None:
                current = next((i for i, t in enumerate(self.results) if t['id'] == self.current['id']), None)
                if current is not None:
                    return self.play_result(current + (2 if action == 'next' else 0))
            else:
                button.click(timeout=4000)
                deadline = time.monotonic() + self.timeout
                while time.monotonic() < deadline:
                    self.page.wait_for_timeout(150)
                    selected = self.now_track()
                    if selected and (key(selected['title']), key(selected['artist'])) != (key(self.current['title']), key(self.current['artist'])):
                        playing = self.progressing(before, after_sequence=sequence)
                        if playing:
                            self.current = selected
                            return self.playback_result(self.current, None, playing, 'playing')
                    before = self.audio()
                self.current = None
                return {'status': 'control_requested', 'action': action, 'playback_verified': False, 'do_not_retry': True}
        raise ServiceError('Нет выбранного трека VK. Сначала попросите включить музыку.')
