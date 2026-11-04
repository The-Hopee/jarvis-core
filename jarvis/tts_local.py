"""Offline Russian male neural speech using the official Silero model."""
from array import array
from pathlib import Path
import re
import urllib.request
import wave

from .config import USER_DIR

MODEL_URL = 'https://models.silero.ai/models/tts/ru/v5_ru.pt'
MODEL_PATH = USER_DIR / 'models/silero-v5-ru.pt'


def download_model(path=MODEL_PATH):
    if path.is_file() and path.stat().st_size > 1000000:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.part')
    try:
        with urllib.request.urlopen(MODEL_URL, timeout=30) as response, temporary.open('wb') as output:
            total = 0
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > 250 * 1024 * 1024:
                    raise RuntimeError('Модель голоса превысила лимит загрузки')
                output.write(chunk)
        if temporary.stat().st_size < 1000000:
            raise RuntimeError('Модель голоса загрузилась не полностью')
        temporary.replace(path)
        return path
    finally:
        temporary.unlink(missing_ok=True)


class LocalVoice:
    def __init__(self, speaker='aidar', model_path=MODEL_PATH):
        self.speaker, self.path, self.model = speaker, model_path, None

    def load(self):
        if self.model is None:
            if not self.path.is_file():
                raise RuntimeError('Локальная модель голоса не установлена: запустите setup-voice.ps1')
            import torch
            torch.set_num_threads(4)
            self.model = torch.package.PackageImporter(str(self.path)).load_pickle('tts_models', 'model')
            self.model.to(torch.device('cpu'))
        return self.model

    def save(self, text, destination, rate='-8%'):
        model = self.load()
        pieces = re.split(r'(?<=[.!?;])\s+', text)
        chunks = []
        for piece in pieces:
            while len(piece) > 500:
                cut = piece.rfind(' ', 0, 480)
                cut = cut if cut > 0 else 480
                chunks.append(piece[:cut])
                piece = piece[cut:].strip()
            if piece.strip():
                chunks.append(piece)
        samples = array('h')
        for chunk in chunks:
            audio = model.apply_tts(text=chunk, speaker=self.speaker, sample_rate=48000)
            samples.extend(int(max(-1, min(1, value)) * 32767) for value in audio.tolist())
            samples.extend([0] * 4800)
        # A small playback-rate reduction deepens and slows the selected male voice.
        speed = max(0.85, min(1.15, 1 + int(rate[:-1]) / 100))
        with wave.open(str(destination), 'wb') as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(round(48000 * speed))
            output.writeframes(samples.tobytes())
        return Path(destination)
