import asyncio
import ctypes
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import uuid

from .config import ROOT


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


async def edge_save(text, voice, path):
    import edge_tts
    communication = edge_tts.Communicate(text, voice, rate="+0%", pitch="-5Hz")
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

    def speak(self, text):
        if self.muted or self.settings.tts == "off":
            return
        text = spoken_text(text)
        if not text:
            return
        if self.settings.tts == "edge" and self.edge_healthy:
            try:
                with tempfile.TemporaryDirectory(prefix="jarvis-speech-") as directory:
                    path = Path(directory) / "speech.mp3"
                    asyncio.run(edge_save(text, self.settings.voice, path))
                    play_mp3(path)
                return
            except Exception:
                self.edge_healthy = False
                print("[Голос] Онлайн-синтез недоступен; использую русский голос Windows.", file=sys.stderr)
        try:
            windows_speak(text)
        except (RuntimeError, OSError, subprocess.TimeoutExpired):
            print("[Голос] Озвучивание недоступно. Ответ остаётся в консоли.", file=sys.stderr)
