"""Decode and transcribe the owner's note entirely locally. Never calls a network API."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import av
from vosk import Model,KaldiRecognizer,SetLogLevel
from jarvis.config import Settings,USER_DIR

def main():
    path=Path(sys.argv[1]);SetLogLevel(-1)
    recognizer=KaldiRecognizer(Model(str(Settings.load().model_path)),16000)
    resampler=av.AudioResampler(format='s16',layout='mono',rate=16000)
    parts=[];samples=0
    with path.open('rb') as file,av.open(file) as container:
        for frame in container.decode(audio=0):
            for converted in resampler.resample(frame):
                samples+=converted.samples
                if recognizer.AcceptWaveform(converted.to_ndarray().tobytes()):
                    text=json.loads(recognizer.Result()).get('text','')
                    if text:parts.append(text)
    for frame in resampler.resample(None):recognizer.AcceptWaveform(frame.to_ndarray().tobytes())
    final=json.loads(recognizer.FinalResult()).get('text','')
    if final:parts.append(final)
    output=USER_DIR/'notes/2026-11-05-idea-local.txt';output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text('\n'.join(parts)+'\n',encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps({'duration_seconds':round(samples/16000,1),'local_only':True,'text':'\n'.join(parts)},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
