"""Render short public preview phrases offline; no audio playback."""
import json
import os
from dataclasses import replace
from pathlib import Path
import sys
import time
import wave
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from jarvis.config import Settings,USER_DIR
from jarvis.local_ai import LocalAI


def main():
    os.environ['JARVIS_LOCAL_DIAGNOSTICS']='1'
    settings=Settings.load();manifest=json.loads((USER_DIR/'local-model-install.json').read_text(encoding='utf-8'))
    suffix=''
    if '--target-a' in sys.argv:
        folder=USER_DIR/'voice-references/local-target-a'
        settings=replace(settings,voice_reference=str(folder/'approved-a.wav'),
                         voice_reference_text=(folder/'approved-a.txt').read_text(encoding='utf-8'))
        suffix='-target-a'
    model=LocalAI(manifest,90);directory=USER_DIR/'voice-previews';directory.mkdir(parents=True,exist_ok=True)
    result=[]
    try:
        for name,text in [('local-qwen-a'+suffix,'К вашим услугам, сэр.'),('local-qwen-message'+suffix,'Сообщение отправлено, сэр.')]:
            path=directory/(name+'.wav');path.unlink(missing_ok=True);start=time.monotonic()
            model.voice.synthesize(text,path,settings)
            with wave.open(str(path)) as audio:
                seconds=audio.getnframes()/audio.getframerate();rate=audio.getframerate()
            row={'file':path.name,'seconds_to_render':round(time.monotonic()-start,3),
                 'audio_seconds':round(seconds,3),'sample_rate':rate,'bytes':path.stat().st_size}
            result.append(row);print(json.dumps(row),flush=True)
            if not .3<=seconds<=15:raise RuntimeError('Short voice preview duration is outside expected range')
        before=model.status();model.close();after=model.status()
        report={'previews':result,'before_exit':before,'after_exit':after,'playback':False,'passed':True}
        (USER_DIR/('benchmarks/local-voice-real-smoke'+suffix+'.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report),flush=True);return 0
    except Exception:
        for line in getattr(model.voice,'last_error_details',[]):print(line,file=sys.stderr)
        raise
    finally:model.close()


if __name__=='__main__':raise SystemExit(main())
