"""Synthesize a fixed Russian phrase and transcribe the WAV locally, without a microphone."""
import json
from pathlib import Path
import sys
import tempfile
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis.config import Settings
from jarvis.speech import windows_speak
from jarvis.voice import WakeGate
from jarvis.assistant import local_intent


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    import vosk
    vosk.SetLogLevel(-1)
    settings = Settings.load()
    model = vosk.Model(str(settings.model_path))
    phrases = ['Джарвис, состояние машины.', 'Джарвис, открой ютуб.',
               'Джарвис, открой телеграм.', 'Джарвис, какая погода?']
    reports = []
    expected_tools = ['get_system_status', 'open_website', 'open_application', 'get_weather']
    with tempfile.TemporaryDirectory(prefix='jarvis-voice-check-') as directory:
        for index, phrase in enumerate(phrases):
            path = Path(directory) / f'phrase-{index}.wav'
            voice = windows_speak(phrase, path)
            with wave.open(str(path), 'rb') as audio:
                assert audio.getnchannels() == 1 and audio.getsampwidth() == 2
                recognizer = vosk.KaldiRecognizer(model, audio.getframerate())
                texts = []
                while chunk := audio.readframes(4000):
                    if recognizer.AcceptWaveform(chunk):
                        texts.append(json.loads(recognizer.Result()).get('text', ''))
                texts.append(json.loads(recognizer.FinalResult()).get('text', ''))
            recognized = ' '.join(filter(None, texts))
            command = WakeGate().accept(recognized)
            intent = local_intent(command) if command else None
            reports.append({'input': phrase, 'recognized': recognized, 'wake_accepted': command is not None,
                            'command': command, 'intent': intent,
                            'intent_correct': bool(intent and intent[0] == expected_tools[index]),
                            'windows_voice': voice['voice']})
    print(json.dumps(reports, ensure_ascii=False, indent=2))
    return 0 if all(report['wake_accepted'] and report['intent_correct'] for report in reports) else 1


if __name__ == '__main__':
    raise SystemExit(main())
