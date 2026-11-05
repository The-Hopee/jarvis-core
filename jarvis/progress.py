"""Cached status clips only. A worker never calls a model or executes tools."""
import asyncio
import hashlib
import json
from pathlib import Path
import threading
import time

from .config import USER_DIR

STATUS_TEXT = {'asr': 'Распознаю команду, сэр.', 'model': 'Готовлю ответ, сэр.',
               'tool': 'Выполняю команду, сэр.', 'tts': 'Готовлю озвучивание, сэр.'}


def cache_directory(settings):
    fields = {k: getattr(settings, k) for k in ('tts', 'tts_model', 'tts_voice', 'voice', 'tts_rate', 'tts_pitch',
              'local_speaker', 'elevenlabs_voice_id', 'elevenlabs_tts_model')}
    fields['reference_text_hash'] = hashlib.sha256(settings.voice_reference_text.encode('utf-8')).hexdigest()
    try:
        reference = Path(settings.voice_reference) if settings.voice_reference else None
        fields['reference_hash'] = (hashlib.sha256(reference.read_bytes()).hexdigest()
                                    if reference and reference.is_file() and reference.stat().st_size <= 10 * 1024 * 1024
                                    else 'missing' if reference else '')
    except OSError:
        fields['reference_hash'] = 'missing'
    fields['texts'] = STATUS_TEXT
    key = hashlib.sha256(json.dumps(fields, sort_keys=True).encode('utf-8')).hexdigest()[:24]
    return USER_DIR / 'voice-statuses' / key


def prepare_status_voice(settings):
    """Explicit one-time command: render chosen voice locally; no playback."""
    from .speech import edge_save, windows_speak
    directory = cache_directory(settings)
    directory.mkdir(parents=True, exist_ok=True)
    suffix = '.mp3' if settings.tts in {'openrouter', 'elevenlabs', 'edge'} else '.wav'
    paths = []
    if settings.tts == 'off':
        return paths
    for kind, text in STATUS_TEXT.items():
        path = directory / (kind + suffix)
        if path.is_file() and 100 < path.stat().st_size <= 512 * 1024:
            paths.append(str(path))
            continue
        temporary = path.with_name(kind + '.part' + suffix)
        try:
            if settings.tts in {'openrouter', 'elevenlabs'}:
                from .cloud_voice import OpenRouterVoice, CloudVoice
                provider = OpenRouterVoice if settings.tts == 'openrouter' else CloudVoice
                provider(settings).synthesize(text, temporary)
            elif settings.tts == 'edge':
                asyncio.run(edge_save(text, settings.voice, temporary, rate=settings.tts_rate, pitch=settings.tts_pitch))
            elif settings.tts == 'silero':
                from .tts_local import LocalVoice
                LocalVoice(settings.local_speaker).save(text, temporary, rate=settings.tts_rate)
            else:
                windows_speak(text, temporary)
            if not temporary.is_file() or not 100 < temporary.stat().st_size <= 512 * 1024:
                raise RuntimeError('Не удалось подготовить короткую голосовую реплику')
            temporary.replace(path)
            paths.append(str(path))
        finally:
            temporary.unlink(missing_ok=True)
    return paths


class ProgressFeedback:
    def __init__(self, speaker, *, delay=0.8, interval=8, enabled=True, stopped=None):
        self.speaker, self.delay, self.interval, self.enabled = speaker, delay, interval, enabled
        self.stopped = stopped or (lambda: False)
        self.cancelled = threading.Event()
        self.thread, self.trace = None, None

    def start(self, trace):
        if not self.enabled or self.thread is not None or self.cancelled.is_set():
            return
        self.trace = trace
        self.thread = threading.Thread(target=self._run, name='jarvis-status', daemon=True)
        self.thread.start()

    def _run(self):
        if self.cancelled.wait(self.delay):
            return
        seen, last = set(), float('-inf')
        while not self.cancelled.is_set() and not self.stopped():
            phase = self.trace.phase()
            kind = phase[0]
            if kind in STATUS_TEXT and kind not in seen and time.monotonic() - last >= self.interval:
                seen.add(kind)
                relevant = lambda: not self.cancelled.is_set() and not self.stopped() and self.trace.phase() == phase
                try:
                    with self.trace.activate():
                        played = self.speaker.play_status(kind, relevant)
                    if played:
                        last = time.monotonic()
                except Exception:
                    # A missing/corrupt cache cannot affect the actual task.
                    pass
            if self.cancelled.wait(.05):
                return

    def stop(self):
        self.cancelled.set()
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(timeout=7)
