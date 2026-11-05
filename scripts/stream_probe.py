"""Measure live first PCM and end of download without making any sound."""
from pathlib import Path
import json
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from jarvis.config import Settings,USER_DIR
from jarvis.cloud_voice import OpenRouterVoice
from jarvis.audio_stream import decode_mp3

settings=Settings.load()
rows=[]
for phrase in ('Проверка потока. Я на связи, сэр.','Системы работают нормально. Готов приступить к следующей задаче.'):
    start=time.monotonic();first=None;total=0;chunks=0
    for pcm in decode_mp3(OpenRouterVoice(settings).stream(phrase)):
        if first is None:first=time.monotonic()
        total+=len(pcm);chunks+=1
    rows.append({'first_pcm_ms':round((first-start)*1000,3),'complete_ms':round((time.monotonic()-start)*1000,3),
                 'audio_seconds':round(total/48000,3),'pcm_chunks':chunks,'played':False})
target=USER_DIR/'benchmarks/stage06-stream-probe.json'
target.write_text(json.dumps({'model':settings.tts_model,'voice_reference_preserved':True,'records':rows},indent=2),encoding='utf-8')
print(json.dumps(rows),flush=True)
