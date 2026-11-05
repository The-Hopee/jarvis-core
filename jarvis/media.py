"""Resolve YouTube requests to a real video URL instead of treating speech as a domain."""
import json
import re
from urllib.parse import urlencode
import urllib.error
import urllib.request

from .http import ServiceError

YOUTUBE_WORD = r"(?:ютуб(?:е|а)?|ютьюб(?:е|а)?|ютюб(?:е|а)?|youtube)"


def youtube_query(text):
    patterns = [
        rf"^(?:открой|открыть|включи|найди|запусти|покажи)\s+(?:мне\s+)?(?:на\s+)?{YOUTUBE_WORD}\s+(?:(?:видео|клип|ролик)\s+)?(.+)$",
        rf"^(?:открой|открыть|включи|найди|запусти|покажи)\s+(?:(?:видео|клип|ролик)\s+)?(.+?)\s+на\s+{YOUTUBE_WORD}$",
    ]
    for pattern in patterns:
        match = re.match(pattern, text.strip().strip('.,!?'), re.I)
        if match:
            query = match[1].strip(' ,.!?')
            if query and query.casefold() not in {'видео', 'клип', 'ролик'}:
                return query
    return None


def fetch_html(url):
    from .privacy import check_url
    check_url(url)
    request = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 JarvisHome/0.3', 'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.5'})
    try:
        with urllib.request.urlopen(request, timeout=18) as response:
            data = response.read(8 * 1024 * 1024 + 1)
        if len(data) > 8 * 1024 * 1024:
            raise ServiceError('Ответ YouTube слишком большой')
        return data.decode('utf-8')
    except (urllib.error.URLError, TimeoutError, OSError, UnicodeError) as exc:
        raise ServiceError('Поиск YouTube недоступен. Проверьте подключение к YouTube/VPN.') from exc


def _text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get('simpleText') or value.get('content') or ''.join(run.get('text', '') for run in value.get('runs', []))
    return ''


def parse_videos(html, limit=5):
    state = None
    for match in re.finditer(r'(?:var\s+)?ytInitialData\s*=\s*|window\["ytInitialData"\]\s*=\s*', html):
        try:
            state, _ = json.JSONDecoder().raw_decode(html, match.end())
            break
        except ValueError:
            continue
    if state is None:
        raise ServiceError('YouTube не предоставил результаты: возможно, требуется вход или проверка браузера.')
    found, seen = [], set()
    excluded = {'adSlotRenderer', 'promotedSparklesWebRenderer', 'searchPyvRenderer', 'adPlacementRenderer'}

    def visit(value):
        if len(found) >= limit:
            return
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            if excluded.intersection(value):
                return
            video = value.get('videoRenderer')
            if isinstance(video, dict):
                add(video.get('videoId'), _text(video.get('title', {})), _text(video.get('ownerText', {})))
                return
            lockup = value.get('lockupViewModel')
            if isinstance(lockup, dict) and lockup.get('contentType') == 'LOCKUP_CONTENT_TYPE_VIDEO':
                metadata = lockup.get('metadata', {}).get('lockupMetadataViewModel', {})
                add(lockup.get('contentId'), _text(metadata.get('title', {})), '')
                return
            for item in value.values():
                visit(item)

    def add(video_id, title, channel):
        if isinstance(video_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id) and title and video_id not in seen:
            seen.add(video_id)
            found.append({'video_id': video_id, 'title': title[:300], 'channel': channel[:200],
                          'url': 'https://www.youtube.com/watch?v=' + video_id})

    visit(state.get('contents', state))
    return found[:limit]


class YouTube:
    def __init__(self, kernel, fetch=fetch_html):
        self.kernel, self.fetch = kernel, fetch
        self.last_results = None

    def search(self, query, limit=5):
        url = 'https://www.youtube.com/results?' + urlencode({'search_query': query, 'hl': 'ru'})
        videos = parse_videos(self.fetch(url), limit)
        if not videos:
            raise ServiceError('YouTube не вернул подходящих видео. Уточните исполнителя или название.')
        self.last_results = {'query': query, 'videos': videos, 'search_url': url}
        return self.last_results

    def open_video(self, query, index=1):
        self.search(query, limit=max(index, 5))
        return self.open_result(index)

    def open_result(self, index=1):
        results = self.last_results
        if not results:
            raise ServiceError('Сначала попроси найти видео; предыдущих результатов пока нет')
        if index > len(results['videos']):
            raise ServiceError('В результатах нет видео с таким номером')
        video = results['videos'][index - 1]
        launched = self.kernel.call('open_url', {'url': video['url']})['result']
        return {**video, 'query': results['query'], 'selection': 'search_result', 'result_index': index,
                'status': launched['status'], 'page_loaded_verified': False}
