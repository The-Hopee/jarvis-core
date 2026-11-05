from dataclasses import dataclass, field
import os
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
USER_DIR = Path(os.environ.get('JARVIS_DATA_DIR') or str(Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Jarvis")).resolve()
if getattr(sys,'frozen',False):os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH',str(USER_DIR/'browsers'))


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
    master_model: str = ""
    worker_model: str = ""
    review_model: str = ""
    document_model: str = 'openai/gpt-6.1-terra'
    coding_model: str = 'openai/gpt-6-sol'
    document_effort: str = 'low'
    coding_effort: str = 'high'
    light_budget: float = .10
    document_budget: float = .30
    coding_budget: float = 1.0
    tts: str = "edge"
    voice: str = "ru-RU-DmitryNeural"
    voice_preset: str = "deep"
    tts_rate: str = "-8%"
    tts_pitch: str = "-18Hz"
    local_speaker: str = "aidar"
    city: str = ""
    latitude: float | None = None
    longitude: float | None = None
    microphone: int | str | None = None
    telegram_path: str = ""
    telegram_api_id: int | None = None
    telegram_api_hash: str = field(default="", repr=False)
    asr: str = "vosk"
    asr_model: str = "elevenlabs/scribe-v2"
    tts_model: str = "fish-audio/s2.1-pro"
    tts_voice: str = ""
    voice_reference: str = ""
    voice_reference_text: str = ""
    voice_samples: str = ""
    elevenlabs_api_key: str = field(default="", repr=False)
    elevenlabs_voice_id: str = ""
    elevenlabs_tts_model: str = "eleven_multilingual_v2"
    elevenlabs_asr_model: str = "scribe_v2"
    conversation_seconds: int = 40
    progress_enabled: bool = True
    progress_delay: float = 0.8
    tts_streaming: bool = True
    llm_streaming: bool = True
    document_roots: tuple[Path, ...] = (Path.home() / "Documents",)
    vscode_path: str = ""
    onlyoffice_path: str = ""
    model_path: Path = ROOT / "models" / "vosk-model-small-ru-0.22"

    @property
    def executable(self) -> Path:
        return self.root / "build/bin/Release/jarvis-core.exe"

    @classmethod
    def load(cls, root: Path = ROOT):
        values = {**read_env(USER_DIR / "settings.env"), **read_env(root / ".env"), **os.environ}
        latitude = values.get("JARVIS_LATITUDE", "").strip()
        profile_values={
            'document_model':values.get('JARVIS_DOCUMENT_MODEL','openai/gpt-6.1-terra').strip(),
            'coding_model':values.get('JARVIS_CODING_MODEL','openai/gpt-6-sol').strip(),
            'document_effort':values.get('JARVIS_DOCUMENT_EFFORT','low').strip(),
            'coding_effort':values.get('JARVIS_CODING_EFFORT','high').strip(),
        }
        for name,default in [('light_budget',.10),('document_budget',.30),('coding_budget',1.0)]:
            value=float(values.get('JARVIS_'+name.upper()+'_USD',str(default)))
            if not math.isfinite(value) or not .01<=value<=5:raise ValueError('Лимит профиля: 0.01–5 USD')
            profile_values[name]=value
        if any(profile_values[n] not in {'none','low','medium','high','xhigh','max'} for n in ('coding_effort','document_effort')):
            raise ValueError('Неизвестный уровень reasoning effort')
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
        if tts not in {"silero", "edge", "windows", "elevenlabs", "openrouter", "off"}:
            raise ValueError("JARVIS_TTS: silero, edge, windows, elevenlabs, openrouter или off")
        asr = values.get("JARVIS_ASR", "vosk").strip()
        if asr not in {"vosk", "elevenlabs", "openrouter"}:
            raise ValueError("JARVIS_ASR: vosk, elevenlabs или openrouter")
        conversation_seconds = int(values.get("JARVIS_CONVERSATION_SECONDS", "40"))
        if not 0 <= conversation_seconds <= 180:
            raise ValueError("JARVIS_CONVERSATION_SECONDS: от 0 до 180")
        progress = values.get('JARVIS_PROGRESS', '1').strip()
        tts_streaming=values.get('JARVIS_TTS_STREAMING','1').strip()
        llm_streaming=values.get('JARVIS_LLM_STREAMING','1').strip()
        progress_delay = float(values.get('JARVIS_PROGRESS_DELAY', '0.8'))
        if progress not in {'0', '1'} or tts_streaming not in {'0','1'} or llm_streaming not in {'0','1'} or not math.isfinite(progress_delay) or not .2 <= progress_delay <= 10:
            raise ValueError('JARVIS_PROGRESS: 0 или 1; JARVIS_PROGRESS_DELAY: от 0.2 до 10 секунд')
        document_roots = tuple(Path(p.strip()).expanduser().resolve() for p in
                               values.get("JARVIS_DOCUMENT_ROOTS", str(Path.home() / "Documents")).split(";") if p.strip())
        if not document_roots or len(document_roots) > 10 or any(str(p).startswith("\\\\") for p in document_roots):
            raise ValueError("JARVIS_DOCUMENT_ROOTS: от 1 до 10 локальных каталогов через ;")
        local_speaker = values.get("JARVIS_LOCAL_SPEAKER", "aidar").strip()
        if local_speaker not in {"aidar", "eugene"}:
            raise ValueError("JARVIS_LOCAL_SPEAKER: aidar или eugene")
        preset = values.get("JARVIS_VOICE_PRESET", "deep").strip()
        presets = {"normal": ("+0%", "-5Hz"), "deep": ("-8%", "-18Hz"), "cinematic": ("-12%", "-24Hz")}
        if preset not in presets:
            raise ValueError("JARVIS_VOICE_PRESET: normal, deep или cinematic")
        rate = values.get("JARVIS_TTS_RATE", "").strip() or presets[preset][0]
        pitch = values.get("JARVIS_TTS_PITCH", "").strip() or presets[preset][1]
        if not re.fullmatch(r"[+-]\d{1,2}%", rate) or not -30 <= int(rate[:-1]) <= 30:
            raise ValueError("JARVIS_TTS_RATE: от -30% до +30%")
        if not re.fullmatch(r"[+-]\d{1,2}Hz", pitch) or not -50 <= int(pitch[:-2]) <= 50:
            raise ValueError("JARVIS_TTS_PITCH: от -50Hz до +50Hz")
        return cls(root=root, api_key=values.get("OPENROUTER_API_KEY", "").strip(),**profile_values,
                   model=values.get("OPENROUTER_MODEL", "").strip() or "openai/gpt-4.1-mini",
                   master_model=values.get("JARVIS_MASTER_MODEL", "").strip(),
                   worker_model=values.get("JARVIS_WORKER_MODEL", "").strip(),
                   review_model=values.get("JARVIS_REVIEW_MODEL", "").strip(),
                   tts=tts, voice=values.get("JARVIS_VOICE", "ru-RU-DmitryNeural"),
                   voice_preset=preset, tts_rate=rate, tts_pitch=pitch,
                   local_speaker=local_speaker,
                   city=values.get("JARVIS_CITY", "").strip(), latitude=lat, longitude=lon,
                   microphone=microphone, telegram_path=values.get("JARVIS_TELEGRAM_PATH", "").strip(),
                   telegram_api_id=int(values["TELEGRAM_API_ID"]) if values.get("TELEGRAM_API_ID", "").strip() else None,
                   telegram_api_hash=values.get("TELEGRAM_API_HASH", "").strip(),
                   asr=asr, elevenlabs_api_key=values.get("ELEVENLABS_API_KEY", "").strip(),
                   asr_model=values.get("JARVIS_ASR_MODEL", "elevenlabs/scribe-v2").strip(),
                   tts_model=values.get("JARVIS_TTS_MODEL", "fish-audio/s2.1-pro").strip(),
                   tts_voice=values.get("JARVIS_TTS_VOICE", "").strip(),
                   voice_reference=values.get("JARVIS_VOICE_REFERENCE", "").strip(),
                   voice_reference_text=values.get("JARVIS_VOICE_REFERENCE_TEXT", "").strip(),
                   voice_samples=values.get("JARVIS_VOICE_SAMPLES", "").strip(),
                   elevenlabs_voice_id=values.get("ELEVENLABS_VOICE_ID", "").strip(),
                   elevenlabs_tts_model=values.get("ELEVENLABS_TTS_MODEL", "eleven_multilingual_v2").strip(),
                   elevenlabs_asr_model=values.get("ELEVENLABS_ASR_MODEL", "scribe_v2").strip(),
                   conversation_seconds=conversation_seconds, document_roots=document_roots,
                   progress_enabled=progress == '1', progress_delay=progress_delay,
                   tts_streaming=tts_streaming=='1',
                   llm_streaming=llm_streaming=='1',
                   vscode_path=values.get("JARVIS_VSCODE_PATH", "").strip(),
                   onlyoffice_path=values.get("JARVIS_ONLYOFFICE_PATH", "").strip(),
                   model_path=Path(values.get("JARVIS_VOSK_MODEL", str(root / "models/vosk-model-small-ru-0.22"))))
