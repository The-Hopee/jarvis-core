"""Local Russian ASR. Microphone is open only while listening, never during TTS."""
from collections import deque
from array import array
import json
import math
from pathlib import Path
import queue
import re
import sys
import time
import urllib.request
import zipfile

from .telemetry import TurnTrace, measure, mark

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
        text = text.strip()
        # A name inside dictation ("привет от Джарвис") is data. In a
        # follow-up it must never replace the whole command with a wake ack.
        match = WAKE.match(text)
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
        self.last_trace = None

    def after_response(self, seconds=None):
        # The timer starts after model/TTS latency, giving the user the full
        # configured window. No microphone is open while the assistant speaks.
        self.gate.resume(self.settings.conversation_seconds if seconds is None else seconds)

    def sleep(self):
        self.gate.sleep()

    def _refine(self, command, pcm):
        if not command or self.settings.asr == "vosk" or not self.settings.allow_cloud_asr or self.settings.privacy_mode=='offline_ai' or time.monotonic() < self.cloud_retry_at:
            return command
        try:
            from .cloud_voice import CloudVoice, OpenRouterVoice
            provider = OpenRouterVoice if self.settings.asr == "openrouter" else CloudVoice
            with measure('asr', self.settings.asr_model if self.settings.asr == 'openrouter' else self.settings.elevenlabs_asr_model):
                transcript = provider(self.settings).transcribe(pcm, self.sample_rate)
            match = WAKE.match(transcript.lstrip())
            if match:
                transcript = transcript.lstrip()[match.end():].lstrip(" ,.!?:—-").strip()
            if not transcript:
                return ""  # An empty cloud transcription must not execute a command.
            return transcript
        except RuntimeError as exc:
            mark('asr_fallback')
            self.cloud_retry_at = time.monotonic() + 60
            print("[Распознавание] " + str(exc) + " Использую локальное распознавание.", file=sys.stderr, flush=True)
            return command

    def next_command(self, stop_requested=None, on_accepted=None, interrupt_requested=None):
        import sounddevice as sd
        import vosk
        audio = queue.Queue(maxsize=32)
        errors = queue.Queue(maxsize=4)
        recognizer = vosk.KaldiRecognizer(self.model, self.sample_rate)
        if hasattr(recognizer, 'SetWords'):
            recognizer.SetWords(True)
        self.last_trace = None
        self.last_interrupted=False
        stop_requested = stop_requested or (lambda: False)
        # Keep at most 45 s of the current utterance, never idle room audio on disk.
        chunks = deque()
        buffered = 0
        selected = None
        audio_origin, endpoint, estimated_end = None, None, None
        timing_valid = True
        audio_seconds = 0
        last_acoustic=0
        wake_deadline = None

        def callback(data, frames, timing, status):
            if status:
                try:
                    errors.put_nowait(str(status))
                except queue.Full:
                    pass
            try:
                captured_end = time.monotonic()
                try:
                    # PortAudio clock differences avoid counting input-device
                    # buffering as silence after the user's last word.
                    captured_end -= max(0, timing.currentTime - timing.inputBufferAdcTime - frames / self.sample_rate)
                except (AttributeError, TypeError):
                    pass
                audio.put_nowait((bytes(data), captured_end))
            except queue.Full:
                try:
                    errors.put_nowait('audio_queue_overflow')
                except queue.Full:
                    pass

        # Return closes the stream before the assistant/network/TTS starts.
        with sd.RawInputStream(samplerate=self.sample_rate, blocksize=max(1024, self.sample_rate // 5),
                               device=self.device, dtype="int16", channels=1, callback=callback):
            while True:
                if stop_requested():
                    return None
                try:
                    chunk, captured_end = audio.get(timeout=0.25)
                except queue.Empty:
                    if not errors.empty():
                        raise RuntimeError("Ошибка микрофона: " + errors.get())
                    continue
                chunks.append(chunk)
                duration = len(chunk) / (self.sample_rate * 2)
                audio_seconds += duration
                if audio_origin is None:
                    audio_origin = captured_end - duration
                if not errors.empty():
                    timing_valid = False
                if interrupt_requested is not None or wake_deadline is not None:
                    samples=array('h');samples.frombytes(chunk)
                    if samples and sum(x*x for x in samples)/len(samples)>400*400:
                        last_acoustic=time.monotonic()
                buffered += len(chunk)
                while buffered > self.sample_rate * 2 * 45 and chunks:
                    buffered -= len(chunks.popleft())
                if recognizer.AcceptWaveform(chunk):
                    result = json.loads(recognizer.Result())
                    text = result.get("text", "")
                    if not text:
                        if wake_deadline is None:
                            chunks.clear();buffered = 0
                    else:
                        self.messages.append(text)
                        if wake_deadline is not None:
                            # Speech begun after the wake word can exceed the
                            # short follow-up window before ASR finalizes it.
                            self.gate.resume()
                        command = self.gate.accept(text)
                        if command is not None:
                            selected = command, b"".join(chunks)
                            endpoint = time.monotonic()
                            words = result.get('result', [])
                            last_word = words[-1].get('end') if words and isinstance(words[-1], dict) else None
                            if timing_valid and isinstance(last_word, (int, float)) and math.isfinite(last_word) and 0 <= last_word <= audio_seconds:
                                estimated_end = min(endpoint, audio_origin + last_word)
                            if command:
                                break
                            # Vosk can finalize just "Джарвис" at a short pause.
                            # Keep the microphone open for the rest, before TTS.
                            wake_deadline = endpoint + 1.2
                        elif wake_deadline is None:
                            chunks.clear();buffered = 0
                if wake_deadline is not None:
                    partial = json.loads(recognizer.PartialResult()).get('partial','') if hasattr(recognizer,'PartialResult') else ''
                    if time.monotonic() >= wake_deadline and not partial and time.monotonic()-last_acoustic > .4:
                        break
                    continue
                if interrupt_requested is not None and interrupt_requested():
                    partial=json.loads(recognizer.PartialResult()).get('partial','') if hasattr(recognizer,'PartialResult') else ''
                    if not partial and time.monotonic()-last_acoustic>.6:
                        self.last_interrupted=True
                        return None
        if stop_requested():
            return None
        if selected is None:
            return None
        self.last_trace = TurnTrace('voice', origin=estimated_end if estimated_end is not None else endpoint,
                                    speech_end_source='vosk_word_end_estimate' if estimated_end is not None else 'endpoint_only')
        with self.last_trace.activate():
            mark('endpoint_final', at=endpoint)
            if on_accepted is not None and selected[0]:
                on_accepted(self.last_trace)
            command = self._refine(*selected)
            mark('asr_final')
            return command
