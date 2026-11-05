"""Speak completed sentences while a known text-only response is arriving."""
import queue
import re
import threading


class SentenceSpeech:
    def __init__(self,speaker,feedback,trace,stopped):
        self.speaker,self.feedback,self.trace,self.stopped=speaker,feedback,trace,stopped
        self.queue=queue.Queue(maxsize=4)
        self.cancelled=threading.Event()
        self.buffer='';self.characters=0;self.started=False;self.failed=False;self.thread=None;self.closed=False

    def feed(self,text):
        if self.closed or self.cancelled.is_set():return
        remaining=2400-self.characters
        text=text[:max(0,remaining)];self.characters+=len(text);self.buffer+=text
        while match:=re.search(r'(?<!\d)[.!?]\s+',self.buffer):
            end=match.end()
            if end<12:break
            self._submit(self.buffer[:end].strip());self.buffer=self.buffer[end:]

    def _submit(self,text):
        if not text:return
        if self.thread is None:
            self.thread=threading.Thread(target=self._run,name='jarvis-sentences',daemon=True);self.thread.start()
        while not self.cancelled.is_set() and not self.stopped():
            try:self.queue.put(text,timeout=.05);return
            except queue.Full:pass

    def _run(self):
        with self.trace.activate():
            while not self.cancelled.is_set() and not self.stopped():
                try:text=self.queue.get(timeout=.1)
                except queue.Empty:continue
                if text is None:return
                def ready():
                    self.feedback.stop()
                    if self.cancelled.is_set() or self.stopped():return False
                    self.started=True
                    return True
                try:
                    self.speaker.speak(text,before_playback=ready,stopped=lambda:self.cancelled.is_set() or self.stopped())
                except Exception:
                    from .telemetry import mark
                    mark('sentence_stream_failed');self.failed=True;self.cancelled.set();return

    def finish(self,cancel=False):
        if self.closed:
            if cancel:self.cancelled.set()
            return
        if cancel:self.cancelled.set()
        else:
            self._submit(self.buffer.strip())
            if self.thread is not None:
                while not self.cancelled.is_set() and not self.stopped():
                    try:self.queue.put(None,timeout=.05);break
                    except queue.Full:pass
        self.closed=True
        if self.thread is not None:
            self.thread.join(timeout=200)
            if self.thread.is_alive():self.failed=True;self.cancelled.set()
