from dataclasses import dataclass, field
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
USER_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Jarvis"


def read_env(path: Path) -> dict[str, str]:
    """Read literal KEY=value pairs; no shell execution or variable expansion."""
    if not path.is_file():
        return {}
    result = {}
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:]
        key, separator, value = line.partition("=")
        if not separator or not key.strip().replace("_", "a").isalnum():
            raise ValueError(f"Некорректная строка {number} в {path.name}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        result[key.strip()] = value
    return result


@dataclass(frozen=True)
class Settings:
    root: Path = ROOT
    api_key: str = field(default="", repr=False)
    model: str = "openai/gpt-4.1-mini"
    tts: str = "edge"
    voice: str = "ru-RU-DmitryNeural"
    city: str = ""
    latitude: float | None = None
    longitude: float | None = None
    microphone: int | str | None = None
    telegram_path: str = ""
    model_path: Path = ROOT / "models" / "vosk-model-small-ru-0.22"

    @property
    def executable(self) -> Path:
        return self.root / "build/bin/Release/jarvis-core.exe"

    @classmethod
    def load(cls, root: Path = ROOT):
        values = {**read_env(USER_DIR / "settings.env"), **read_env(root / ".env"), **os.environ}
        latitude = values.get("JARVIS_LATITUDE", "").strip()
        longitude = values.get("JARVIS_LONGITUDE", "").strip()
        if bool(latitude) != bool(longitude):
            raise ValueError("Укажите обе координаты JARVIS_LATITUDE и JARVIS_LONGITUDE")
        lat, lon = (float(latitude), float(longitude)) if latitude else (None, None)
        if lat is not None and not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("Координаты вне допустимого диапазона")
        microphone = values.get("JARVIS_MICROPHONE", "").strip() or None
        if microphone and microphone.isdecimal():
            microphone = int(microphone)
        tts = values.get("JARVIS_TTS", "edge").strip()
        if tts not in {"edge", "windows", "off"}:
            raise ValueError("JARVIS_TTS: edge, windows или off")
        return cls(root=root, api_key=values.get("OPENROUTER_API_KEY", "").strip(),
                   model=values.get("OPENROUTER_MODEL", "").strip() or "openai/gpt-4.1-mini",
                   tts=tts, voice=values.get("JARVIS_VOICE", "ru-RU-DmitryNeural"),
                   city=values.get("JARVIS_CITY", "").strip(), latitude=lat, longitude=lon,
                   microphone=microphone, telegram_path=values.get("JARVIS_TELEGRAM_PATH", "").strip(),
                   model_path=Path(values.get("JARVIS_VOSK_MODEL", str(root / "models/vosk-model-small-ru-0.22"))))
