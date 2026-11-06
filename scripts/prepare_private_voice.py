"""Render only a fixed whitelist of non-private phrases, with no playback."""
import json
from pathlib import Path
import sys
import time
import wave
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from jarvis.config import Settings,USER_DIR
from jarvis.local_ai import LocalAI
from jarvis.local_voice_cache import PHRASES,cached_reply


def main():
    settings=Settings.load();manifest=json.loads((USER_DIR/'local-model-install.json').read_text(encoding='utf-8'))
    models=LocalAI(manifest,90);rows=[]
    try:
        for index,text in enumerate(PHRASES):
            path=cached_reply(settings,text);path.parent.mkdir(parents=True,exist_ok=True)
            if path.exists():continue
            start=time.monotonic();models.voice.synthesize(text,path,settings)
            with wave.open(str(path)) as audio:duration=audio.getnframes()/audio.getframerate()
            if not .1<duration<15:
                path.unlink(missing_ok=True);raise RuntimeError('Cached acknowledgement too long')
            rows.append({'index':index,'render_s':round(time.monotonic()-start,2),'audio_s':round(duration,2)})
            print(json.dumps(rows[-1]),flush=True)
        print(json.dumps({'cached':sum(cached_reply(settings,t).is_file() for t in PHRASES)}),flush=True)
    finally:models.close()


if __name__=='__main__':main()
