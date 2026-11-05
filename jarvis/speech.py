import asyncio
import ctypes
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import uuid

from .config import ROOT


def speech_key(text):
    return " ".join(re.findall(r"\w+", text.casefold().replace("ё", "е")))


def spoken_text(text):
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", "ссылка в консоли", text)
    text = re.sub(r"[*_`#]", "", text)
    return re.sub(r"\s+", " ", text).strip()[:2400]


def windows_speak(text: str, output_path: Path | None = None):
    request = {"text": text}
    if output_path is not None:
        request["output_path"] = str(output_path.resolve())
    result = subprocess.run(["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-File", str(ROOT / "scripts/windows_speech.ps1")],
                            input=json.dumps(request, ensure_ascii=False), text=True, encoding="utf-8",
                            capture_output=True, timeout=180, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        response = json.loads(result.stdout.lstrip("\ufeff"))
    except ValueError as exc:
        raise RuntimeError("Не удалось запустить голос Windows") from exc
    if result.returncode or not response.get("ok"):
        raise RuntimeError("Синтез речи Windows недоступен")
    return response


async def edge_save(text, voice, path, rate="+0%", pitch="-5Hz"):
    import edge_tts
    communication = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await asyncio.wait_for(communication.save(str(path)), timeout=20)


def play_mp3(path):
    winmm = ctypes.WinDLL("winmm")
    send = winmm.mciSendStringW
    send.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_void_p]
    send.restype = ctypes.c_uint
    alias = "jarvis_" + uuid.uuid4().hex
    error = send(f'open "{path}" type mpegvideo alias {alias}', None, 0, None)
    if error:
        raise RuntimeError("Windows не смог открыть звуковой файл")
    try:
        if send(f"play {alias} wait", None, 0, None):
            raise RuntimeError("Ошибка воспроизведения речи")
    finally:
        send(f"close {alias}", None, 0, None)


class Speaker:
    def __init__(self, settings, muted=False):
        self.settings, self.muted = settings, muted
        self.edge_healthy = True
        self.local_voice = None
        self.cloud_retry_at = 0
        self.recordings = None

    def _play_recording(self, text):
        if not self.settings.voice_samples:
            return False
        try:
            manifest = Path(self.settings.voice_samples).expanduser().resolve()
            if self.recordings is None:
                if manifest.stat().st_size > 256 * 1024:
                    raise ValueError("Слишком большой список реплик")
                data = json.loads(manifest.read_text(encoding="utf-8-sig"))["samples"]
                if not isinstance(data, dict) or len(data) > 200:
                    raise ValueError("Некорректный список реплик")
                self.recordings = {speech_key(key): value for key, value in data.items()
                                   if isinstance(key, str) and isinstance(value, str)}
            relative = self.recordings.get(speech_key(text))
            if relative is None:
                return False
            path = (manifest.parent / relative).resolve()
            if not path.is_relative_to(manifest.parent) or not path.is_file() or path.stat().st_size > 5 * 1024 * 1024:
                raise ValueError("Аудиореплика вне каталога или превышает лимит")
            if path.suffix.lower() == ".wav":
                import winsound
                winsound.PlaySound(str(path), winsound.SND_FILENAME)
            elif path.suffix.lower() == ".mp3":
                play_mp3(path)
            else:
                raise ValueError("Нужен WAV или MP3")
            return True
        except (OSError, ValueError, KeyError, TypeError, RuntimeError):
            self.recordings = {}
            print("[Голос] Записанная реплика недоступна; использую синтез речи.", file=sys.stderr)
            return False

    def speak(self, text):
        if self.muted or self.settings.tts == "off":
            return
        text = spoken_text(text)
        if not text:
            return
        if self._play_recording(text):
            return
        if self.settings.tts in {"elevenlabs", "openrouter"} and time.monotonic() >= self.cloud_retry_at:
            try:
                from .cloud_voice import CloudVoice, OpenRouterVoice
                with tempfile.TemporaryDirectory(prefix="jarvis-cloud-voice-") as directory:
                    path = Path(directory) / "speech.mp3"
                    provider = OpenRouterVoice if self.settings.tts == "openrouter" else CloudVoice
                    provider(self.settings).synthesize(text, path)
                    play_mp3(path)
                return
            except (RuntimeError, OSError):
                self.cloud_retry_at = time.monotonic() + 60
                print("[Голос] Выбранный облачный голос недоступен; использую локальный мужской голос. Проверьте настройки ключа и выбранного голоса.", file=sys.stderr)
        if self.settings.tts in {"silero", "elevenlabs", "openrouter"}:
            try:
                from .tts_local import LocalVoice
                import winsound
                if self.local_voice is None:
                    self.local_voice = LocalVoice(self.settings.local_speaker)
                with tempfile.TemporaryDirectory(prefix="jarvis-local-voice-") as directory:
                    path = Path(directory) / "speech.wav"
                    self.local_voice.save(text, path, rate=self.settings.tts_rate)
                    winsound.PlaySound(str(path), winsound.SND_FILENAME)
                return
            except Exception:
                print("[Голос] Локальный нейроголос недоступен; использую Windows.", file=sys.stderr)
        if self.settings.tts == "edge" and self.edge_healthy:
            try:
                with tempfile.TemporaryDirectory(prefix="jarvis-speech-") as directory:
                    path = Path(directory) / "speech.mp3"
                    asyncio.run(edge_save(text, self.settings.voice, path,
                                          rate=self.settings.tts_rate, pitch=self.settings.tts_pitch))
                    play_mp3(path)
                return
            except Exception:
                self.edge_healthy = False
                print("[Голос] Онлайн-синтез недоступен; использую русский голос Windows.", file=sys.stderr)
        try:
            windows_speak(text)
        except (RuntimeError, OSError, subprocess.TimeoutExpired):
            print("[Голос] Озвучивание недоступно. Ответ остаётся в консоли.", file=sys.stderr)


def voice_previews(settings):
    from .config import USER_DIR
    directory = USER_DIR / "voice-previews"
    directory.mkdir(parents=True, exist_ok=True)
    text = "Системы в норме. Я на связи. Готов приступить к выполнению вашей задачи."
    results = []
    if settings.tts in {"elevenlabs", "openrouter"}:
        from .cloud_voice import CloudVoice, OpenRouterVoice
        path = directory / "selected-cloud-voice.mp3"
        provider = OpenRouterVoice if settings.tts == "openrouter" else CloudVoice
        provider(settings).synthesize(text, path)
        return [{"backend": settings.tts, "path": str(path)}]
    if settings.tts == "silero":
        from .tts_local import LocalVoice
        for speaker in ("aidar", "eugene"):
            path = directory / (speaker + ".wav")
            LocalVoice(speaker).save(text, path, rate=settings.tts_rate)
            results.append({"speaker": speaker, "path": str(path)})
        return results
    for name, rate, pitch in (("normal", "+0%", "-5Hz"), ("deep", "-8%", "-18Hz"),
                              ("cinematic", "-12%", "-24Hz")):
        path = directory / (name + ".mp3")
        try:
            asyncio.run(edge_save(text, settings.voice, path, rate=rate, pitch=pitch))
        except Exception as exc:
            raise RuntimeError("Онлайн-голос сейчас недоступен. Для локального мужского голоса запустите setup-voice.ps1.") from exc
        results.append({"preset": name, "path": str(path), "rate": rate, "pitch": pitch})
    return results
