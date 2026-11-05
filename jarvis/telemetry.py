"""Bounded, content-free per-turn timings. No prompts, arguments or audio."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import threading
import time
import uuid

from .config import USER_DIR

CURRENT = ContextVar('jarvis_trace', default=None)
LOG_PATH = USER_DIR / 'logs/latency.jsonl'
_write_lock = threading.Lock()
_LABEL = re.compile(r'^[a-zA-Z0-9_.:/-]{1,96}$')


def _label(value):
    return value if isinstance(value, str) and _LABEL.fullmatch(value) else 'unknown'


def append_record(record, path=LOG_PATH):
    """One bounded write per turn; failure to write never replays an action."""
    try:
        raw = json.dumps(record, ensure_ascii=True, allow_nan=False) + '\n'
        if len(raw) > 64000:
            return
        with _write_lock:
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.is_file() and path.stat().st_size + len(raw) > 2 * 1024 * 1024:
                path.with_name(path.name + '.3').unlink(missing_ok=True)
                for n in (2, 1):
                    old = path.with_name(path.name + '.' + str(n))
                    if old.exists():
                        old.replace(path.with_name(path.name + '.' + str(n + 1)))
                path.replace(path.with_name(path.name + '.1'))
            with path.open('a', encoding='utf-8') as out:
                out.write(raw)
    except (OSError, ValueError, TypeError):
        pass


class TurnTrace:
    def __init__(self, source='text', *, origin=None, speech_end_source='unavailable', sink=append_record, clock=time.monotonic):
        self.clock, self.sink = clock, sink
        self.origin = clock() if origin is None else origin
        self.request_id = uuid.uuid4().hex
        self.source, self.speech_end_source = _label(source), _label(speech_end_source)
        self.created_at = datetime.now(timezone.utc).isoformat(timespec='milliseconds')
        self.events, self.spans = {}, []
        self._phase = ('idle', '')
        self._lock, self._finished = threading.RLock(), False

    @contextmanager
    def activate(self):
        token = CURRENT.set(self)
        try:
            yield self
        finally:
            CURRENT.reset(token)

    def mark(self, name, *, at=None):
        with self._lock:
            if len(self.events) < 32 and not self._finished:
                self.events.setdefault(_label(name), round(max(0, (self.clock() if at is None else at) - self.origin) * 1000, 3))

    def phase(self):
        with self._lock:
            return self._phase

    @contextmanager
    def measure(self, name, operation='', *, foreground=True):
        start, name, operation = self.clock(), _label(name), _label(operation) if operation else ''
        with self._lock:
            previous = self._phase
            if foreground:
                self._phase = (name, operation)
        outcome = {'status': 'ok'}
        try:
            yield outcome
        except BaseException:
            outcome['status'] = 'error'
            raise
        finally:
            end = self.clock()
            with self._lock:
                if foreground:
                    self._phase = previous
                if len(self.spans) < 128 and not self._finished:
                    self.spans.append({'stage': name, 'operation': operation, 'status': 'error' if outcome['status'] == 'error' else 'ok',
                        'start_ms': round(max(0, start - self.origin) * 1000, 3),
                        'duration_ms': round(max(0, end - start) * 1000, 3)})

    def finish(self, status='completed'):
        with self._lock:
            if self._finished:
                return
            self.mark('turn_end')
            self._finished = True
            summary = {stage + '_ms': round(sum(s['duration_ms'] for s in self.spans if s['stage'] == stage), 3)
                       for stage in ('asr', 'model', 'tool', 'tts', 'playback', 'status_playback')}
            for event in ('endpoint_final', 'asr_final', 'feedback_start', 'answer_ready', 'tts_first_byte', 'answer_playback_start', 'turn_end'):
                if event in self.events:
                    summary[event + '_ms'] = self.events[event]
            record = {'schema_version': 1, 'request_id': self.request_id, 'created_at': self.created_at,
                'source': self.source, 'speech_end_source': self.speech_end_source, 'status': _label(status),
                'events_ms': dict(self.events), 'spans': list(self.spans), 'summary': summary}
        self.sink(record)


@contextmanager
def measure(stage, operation='', *, foreground=True):
    trace = CURRENT.get()
    if trace is None:
        yield {}
    else:
        with trace.measure(stage, operation, foreground=foreground) as outcome:
            yield outcome


def mark(event, *, at=None):
    trace = CURRENT.get()
    if trace is not None:
        trace.mark(event, at=at)


def report(paths, *, source=None):
    """Summarise metadata only. Malformed/oversized records are ignored."""
    records = []
    for path in paths:
        try:
            with Path(path).open(encoding='utf-8') as stream:
                for line in stream:
                    if len(line) > 64000:
                        continue
                    try:
                        r = json.loads(line)
                        if r.get('schema_version') == 1 and isinstance(r.get('summary'), dict) and isinstance(r.get('source'), str) and (source is None or r.get('source') == source):
                            records.append(r)
                    except (ValueError, AttributeError):
                        continue
        except OSError:
            continue
    keys = sorted({k for r in records for k in r.get('summary', {})})
    metrics = {}
    for key in keys:
        vals = sorted(r['summary'][key] for r in records
                      if isinstance(r.get('summary', {}).get(key), (int, float)) and math.isfinite(r['summary'][key]))
        if vals:
            mid = len(vals) // 2
            metrics[key] = {'n': len(vals), 'p50_ms': round((vals[mid] + vals[(len(vals)-1)//2]) / 2, 3),
                            'p95_ms': vals[math.ceil(len(vals) * .95)-1]}
    return {'turns': len(records), 'sources': {s: sum(r.get('source') == s for r in records) for s in sorted({r.get('source', 'unknown') for r in records})},
            'speech_end_sources': {s:sum(r.get('speech_end_source','unavailable') == s for r in records)
                                  for s in sorted({r.get('speech_end_source','unavailable') for r in records})},
            'metrics': metrics}
