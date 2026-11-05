"""Optional ElevenLabs transport. Only an activated utterance leaves the PC.

The caller controls credentials/voice ID. No voice is labelled as the film voice.
Requests are bounded and never automatically replayed after an uncertain result.
"""
import io
import base64
import json
from pathlib import Path
import re
import urllib.error
import urllib.request
import uuid
import wave

from .http import ServiceError
from .http import request_json
from .telemetry import CURRENT, mark


def wav_bytes(pcm, sample_rate):
    if not 8000 <= sample_rate <= 192000 or not pcm or len(pcm) > sample_rate * 2 * 45 or len(pcm) % 2:
        raise ServiceError("Голосовая команда должна содержать не более 45 секунд PCM16 mono")
    audio = io.BytesIO()
    with wave.open(audio, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return audio.getvalue()


def transcript_text(response):
    try:
        text = response["text"]
        if not isinstance(text, str) or len(text) > 8000:
            raise ValueError()
        return text.strip()
    except (ValueError, KeyError, TypeError) as exc:
        raise ServiceError("Сервис распознавания вернул некорректный текст") from exc


class OpenRouterVoice:
    def __init__(self, settings, http=request_json, audio_transport=None):
        self.settings, self.http = settings, http
        self.audio_transport = audio_transport or request_audio

    def _headers(self):
        if not self.settings.api_key:
            raise ServiceError("Для облачной речи добавьте OPENROUTER_API_KEY в .env")
        return {"Authorization": "Bearer " + self.settings.api_key, "X-Title": "Jarvis Home"}

    def transcribe(self, pcm, sample_rate):
        body = {"model": self.settings.asr_model, "language": "ru", "response_format": "json",
                "input_audio": {"format": "wav", "data": base64.b64encode(wav_bytes(pcm, sample_rate)).decode("ascii")}}
        response = self.http("https://openrouter.ai/api/v1/audio/transcriptions", data=body,
                             headers=self._headers(), timeout=35, max_bytes=128 * 1024)
        return transcript_text(response)

    def speech_body(self, text):
        body = {"model": self.settings.tts_model, "input": text, "response_format": "mp3"}
        if self.settings.voice_reference:
            path = Path(self.settings.voice_reference).expanduser()
            if not path.is_file() or path.suffix.lower() not in {".wav", ".mp3", ".flac", ".ogg", ".m4a"} or not 100 < path.stat().st_size <= 10 * 1024 * 1024:
                raise ServiceError("JARVIS_VOICE_REFERENCE: нужен аудиофайл до 10 MiB")
            body["input_references"] = [{"type": "input_audio", "input_audio": {
                "data": base64.b64encode(path.read_bytes()).decode("ascii"), "format": path.suffix[1:].lower()}}]
            if self.settings.voice_reference_text:
                body["input_references"].append({"type": "text", "text": self.settings.voice_reference_text[:3000]})
        elif self.settings.tts_voice:
            body["voice"] = self.settings.tts_voice
        else:
            raise ServiceError("Выберите JARVIS_VOICE_REFERENCE или JARVIS_TTS_VOICE; голос кино пока не подключён")
        return body

    def stream(self, text):
        yield from stream_audio('https://openrouter.ai/api/v1/audio/speech',
                                data=json.dumps(self.speech_body(text),ensure_ascii=False).encode('utf-8'),
                                headers={**self._headers(),'Content-Type':'application/json','Accept':'audio/mpeg'})

    def synthesize(self, text, destination):
        body = self.speech_body(text)
        raw = self.audio_transport("https://openrouter.ai/api/v1/audio/speech",
                                   data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                   headers={**self._headers(), "Content-Type": "application/json", "Accept": "audio/mpeg"})
        if len(raw) < 100 or raw.lstrip().startswith((b"{", b"<")):
            raise ServiceError("OpenRouter не вернул звуковой файл")
        destination.write_bytes(raw)


def stream_audio(url, *, data, headers, timeout=15, max_bytes=12*1024*1024):
    """Read available chunks, not an entire requested buffer. Never retry."""
    request=urllib.request.Request(url,data=data,headers=headers)
    total=0
    try:
        with urllib.request.urlopen(request,timeout=timeout) as response:
            content_type=response.headers.get('Content-Type','').split(';')[0].lower()
            if content_type not in {'audio/mpeg','audio/mp3','application/octet-stream'}:
                raise ServiceError('Голосовой сервис вернул неподдерживаемый формат потока')
            while True:
                raw=response.read1(4096) if hasattr(response,'read1') else response.read(4096)
                if not raw:
                    break
                if total==0:
                    if raw.lstrip().startswith((b'{',b'<')):
                        raise ServiceError('Голосовой сервис вернул данные вместо аудио')
                    mark('tts_first_byte')
                total+=len(raw)
                if total>max_bytes:
                    raise ServiceError('Голосовой поток превысил лимит')
                yield raw
            if total<100:
                raise ServiceError('Голосовой поток пуст или повреждён')
    except urllib.error.HTTPError as exc:
        raise ServiceError(f'Голосовой сервис: HTTP {exc.code}') from exc
    except (urllib.error.URLError,TimeoutError,OSError) as exc:
        raise ServiceError('Голосовой поток недоступен. Повтор не выполнялся.') from exc


def request_audio(url, *, data, headers, timeout=35, max_bytes=12 * 1024 * 1024):
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            first = response.read(1)
            trace = CURRENT.get()
            if first and trace is not None and trace.phase()[0] == 'tts':
                mark('tts_first_byte')
            raw = first + response.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise ServiceError("Ответ голосового сервиса превысил лимит")
        return raw
    except urllib.error.HTTPError as exc:
        raise ServiceError(f"Голосовой сервис: HTTP {exc.code}. Проверьте ключ, доступ к голосу и баланс.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ServiceError("Голосовой сервис недоступен. Запрос автоматически не повторялся.") from exc


class CloudVoice:
    def __init__(self, settings, transport=request_audio):
        self.settings, self.transport = settings, transport

    def _key(self):
        if not self.settings.elevenlabs_api_key:
            raise ServiceError("Добавьте ELEVENLABS_API_KEY в локальный .env")
        return self.settings.elevenlabs_api_key

    def synthesize(self, text, destination):
        voice_id = self.settings.elevenlabs_voice_id
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", voice_id):
            raise ServiceError("Укажите ELEVENLABS_VOICE_ID выбранного голоса в .env")
        body = {"text": text, "model_id": self.settings.elevenlabs_tts_model,
                "voice_settings": {"stability": 0.65, "similarity_boost": 0.8,
                                   "style": 0.15, "use_speaker_boost": True, "speed": 0.95}}
        raw = self.transport("https://api.elevenlabs.io/v1/text-to-speech/" + voice_id + "?output_format=mp3_44100_128",
                             data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                             headers={"xi-api-key": self._key(), "Content-Type": "application/json", "Accept": "audio/mpeg"})
        if len(raw) < 100 or raw.lstrip().startswith((b"{", b"<")):
            raise ServiceError("Сервис не вернул звуковой файл")
        destination.write_bytes(raw)

    def transcribe(self, pcm, sample_rate):
        audio = wav_bytes(pcm, sample_rate)
        boundary = "jarvis_" + uuid.uuid4().hex
        fields = {"model_id": self.settings.elevenlabs_asr_model, "language_code": "ru",
                  "tag_audio_events": "false", "diarize": "false", "timestamps_granularity": "none"}
        parts = []
        for name, value in fields.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        parts.extend([f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="command.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode(),
                      audio, f'\r\n--{boundary}--\r\n'.encode()])
        raw = self.transport("https://api.elevenlabs.io/v1/speech-to-text", data=b"".join(parts),
                             headers={"xi-api-key": self._key(), "Content-Type": "multipart/form-data; boundary=" + boundary},
                             max_bytes=128 * 1024)
        try:
            return transcript_text(json.loads(raw))
        except (ValueError, KeyError, TypeError) as exc:
            raise ServiceError("Сервис распознавания вернул некорректный текст") from exc
