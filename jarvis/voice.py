"""Local Russian ASR. Microphone is open only while listening, never during TTS."""
from collections import deque
import json
from pathlib import Path
import queue
import re
import sys
import time
import urllib.request
import zipfile

WAKE = re.compile(r"\b(?:джарвис|джервис|джарвиз|jarvis)\b", re.I)
MODEL_NAME = "vosk-model-small-ru-0.22"
MODEL_URL = "https://alphacephei.com/vosk/models/" + MODEL_NAME + ".zip"


def download_model(destination: Path):
    if (destination / "am/final.mdl").is_file():
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    archive_path = destination.parent / (MODEL_NAME + ".zip.part")
    try:
        request = urllib.request.Request(MODEL_URL, headers={"User-Agent": "JarvisHome/0.2"})
        total = 0
        with urllib.request.urlopen(request, timeout=30) as response, archive_path.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > 100 * 1024 * 1024:
                    raise RuntimeError("Архив модели превысил лимит 100 MiB")
                output.write(chunk)
        with zipfile.ZipFile(archive_path) as archive:
            entries = archive.infolist()
            if sum(item.file_size for item in entries) > 300 * 1024 * 1024:
                raise RuntimeError("Модель слишком большая")
            root = destination.parent.resolve()
            for item in entries:
                target = (root / item.filename).resolve()
                if not target.is_relative_to(root) or not item.filename.startswith(MODEL_NAME + "/"):
                    raise RuntimeError("Некорректные пути в архиве модели")
            archive.extractall(root)
        extracted = destination.parent / MODEL_NAME
        if extracted != destination:
            if destination.exists():
                raise RuntimeError("Целевая папка уже существует")
            extracted.rename(destination)
        if not (destination / "am/final.mdl").is_file():
            raise RuntimeError("Архив не содержит ожидаемую модель Vosk")
        return destination
    finally:
        archive_path.unlink(missing_ok=True)


class WakeGate:
    def __init__(self, followup_seconds=8):
        self.followup_seconds = followup_seconds
        self.until = 0

    def resume(self, seconds=None, now=None):
        now = time.monotonic() if now is None else now
        self.until = now + (self.followup_seconds if seconds is None else seconds)

    def sleep(self):
        self.until = 0

    def active(self, now=None):
        return self.until > (time.monotonic() if now is None else now)

    def accept(self, text, now=None):
        now = time.monotonic() if now is None else now
        match = WAKE.search(text)
        if match:
            command = text[match.end():].strip(" ,.!?:—-")
            if command:
                self.until = 0
                return command
            self.until = now + self.followup_seconds
            return ""  # Wake word alone: acknowledge, then wait for a command.
        if self.until and now <= self.until:
            self.until = 0
            return text.strip()
        self.until = 0
        return None


class VoiceInput:
    def __init__(self, settings):
        import sounddevice as sd
        import vosk
        if not (settings.model_path / "am/final.mdl").is_file():
            raise RuntimeError("Нет русской модели. Выполните .\\.venv\\Scripts\\python.exe -m jarvis --download-model")
        vosk.SetLogLevel(-1)
        self.model = vosk.Model(str(settings.model_path))
        self.device = settings.microphone
        info = sd.query_devices(self.device, "input")
        self.sample_rate = int(info["default_samplerate"])
        self.gate = WakeGate()
        self.messages = deque(maxlen=5)
        self.settings = settings
        self.cloud_retry_at = 0

    def after_response(self):
        # The timer starts after model/TTS latency, giving the user the full
        # configured window. No microphone is open while the assistant speaks.
        self.gate.resume(self.settings.conversation_seconds)

    def sleep(self):
        self.gate.sleep()

    def _refine(self, command, pcm):
        if not command or self.settings.asr == "vosk" or time.monotonic() < self.cloud_retry_at:
            return command
        try:
            from .cloud_voice import CloudVoice, OpenRouterVoice
            provider = OpenRouterVoice if self.settings.asr == "openrouter" else CloudVoice
            transcript = provider(self.settings).transcribe(pcm, self.sample_rate)
            match = WAKE.match(transcript.lstrip())
            if match:
                transcript = transcript.lstrip()[match.end():].lstrip(" ,.!?:—-").strip()
            if not transcript:
                return ""  # An empty cloud transcription must not execute a command.
            return transcript
        except RuntimeError as exc:
            self.cloud_retry_at = time.monotonic() + 60
            print("[Распознавание] " + str(exc) + " Использую локальное распознавание.", file=sys.stderr, flush=True)
            return command

    def next_command(self, stop_requested=None):
        import sounddevice as sd
        import vosk
        audio = queue.Queue(maxsize=32)
        errors = queue.Queue(maxsize=4)
        recognizer = vosk.KaldiRecognizer(self.model, self.sample_rate)
        stop_requested = stop_requested or (lambda: False)
        # Keep at most 45 s of the current utterance, never idle room audio on disk.
        chunks = deque()
        buffered = 0
        selected = None

        def callback(data, frames, timing, status):
            if status:
                try:
                    errors.put_nowait(str(status))
                except queue.Full:
                    pass
            try:
                audio.put_nowait(bytes(data))
            except queue.Full:
                pass

        # Return closes the stream before the assistant/network/TTS starts.
        with sd.RawInputStream(samplerate=self.sample_rate, blocksize=max(1024, self.sample_rate // 5),
                               device=self.device, dtype="int16", channels=1, callback=callback):
            while True:
                if stop_requested():
                    return None
                try:
                    chunk = audio.get(timeout=0.25)
                except queue.Empty:
                    if not errors.empty():
                        raise RuntimeError("Ошибка микрофона: " + errors.get())
                    continue
                chunks.append(chunk)
                buffered += len(chunk)
                while buffered > self.sample_rate * 2 * 45 and chunks:
                    buffered -= len(chunks.popleft())
                if recognizer.AcceptWaveform(chunk):
                    text = json.loads(recognizer.Result()).get("text", "")
                    if not text:
                        chunks.clear()
                        buffered = 0
                        continue
                    self.messages.append(text)
                    command = self.gate.accept(text)
                    if command is not None:
                        selected = command, b"".join(chunks)
                        break
                    chunks.clear()
                    buffered = 0
        if stop_requested():
            return None
        return self._refine(*selected) if selected is not None else None
