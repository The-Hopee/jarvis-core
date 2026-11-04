"""Local Russian ASR. Microphone is open only while listening, never during TTS."""
from collections import deque
import json
from pathlib import Path
import queue
import re
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

    def next_command(self, stop_requested=None):
        import sounddevice as sd
        import vosk
        audio = queue.Queue(maxsize=32)
        errors = queue.Queue(maxsize=4)
        recognizer = vosk.KaldiRecognizer(self.model, self.sample_rate)
        stop_requested = stop_requested or (lambda: False)

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
                if recognizer.AcceptWaveform(chunk):
                    text = json.loads(recognizer.Result()).get("text", "")
                    if not text:
                        continue
                    self.messages.append(text)
                    command = self.gate.accept(text)
                    if command is not None:
                        return command
