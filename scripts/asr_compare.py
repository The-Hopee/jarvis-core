"""Silent comparison on synthetic files. No microphone or message sending."""
from dataclasses import replace
import json
from pathlib import Path
import re
import statistics
import sys
import time
import wave

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from jarvis.config import Settings,USER_DIR
from jarvis.cloud_voice import OpenRouterVoice
from scripts.latency_benchmark import CASES


def words(text):
    text=text.casefold().replace('ё','е')
    for pattern,replacement in ((r'\b(?:vs\s*code|вс\s*код)\b','vscode'),(r'\b(?:telegram|телеграмм?)\b','телеграм'),
                                (r'\b(?:youtube|you\s*tube|ютуб)\b','ютуб'),(r'\b(?:python|пайтон|питон)\b','python'),
                                (r'\b(?:джервис|джарвиз|jarvis)\b','джарвис')):
        text=re.sub(pattern,replacement,text)
    return re.findall(r'\w+',text)


def distance(a,b):
    row=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        new=[i]
        for j,y in enumerate(b,1):new.append(min(new[-1]+1,row[j]+1,row[j-1]+(x!=y)))
        row=new
    return row[-1]


def main():
    import vosk
    vosk.SetLogLevel(-1)
    root=USER_DIR/'benchmarks/stage05-release/synthetic-inputs'
    target=USER_DIR/'benchmarks/stage06-asr.json'
    settings=Settings.load()
    local=vosk.Model(str(settings.model_path))
    rows=[]
    for index,expected in enumerate(CASES,1):
        with wave.open(str(root/f'{index:02}.wav'),'rb') as audio:
            rate=audio.getframerate();pcm=audio.readframes(audio.getnframes())
        for name in ('vosk','elevenlabs/scribe-v2','openai/whisper-large-v3-turbo'):
            started=time.monotonic()
            try:
                if name=='vosk':
                    recognizer=vosk.KaldiRecognizer(local,rate)
                    parts=[]
                    for offset in range(0,len(pcm),8000):
                        if recognizer.AcceptWaveform(pcm[offset:offset+8000]):parts.append(json.loads(recognizer.Result()).get('text',''))
                    parts.append(json.loads(recognizer.FinalResult()).get('text',''))
                    text=' '.join(parts)
                else:text=OpenRouterVoice(replace(settings,asr_model=name)).transcribe(pcm,rate)
                expected_words=words(expected)
                row={'case_id':index,'model':name,'ms':round((time.monotonic()-started)*1000,3),
                     'edits':distance(expected_words,words(text)),'words':len(expected_words),'status':'ok',
                     'expected_synthetic_text':expected,'recognized_synthetic_text':text}
            except Exception as exc:
                row={'case_id':index,'model':name,'ms':round((time.monotonic()-started)*1000,3),'status':'error','error_type':type(exc).__name__}
            rows.append(row)
        target.write_text(json.dumps({'records':rows},ensure_ascii=False,indent=2),encoding='utf-8')
        print(f'case {index}/{len(CASES)}',flush=True)
    summary={}
    for name in ('vosk','elevenlabs/scribe-v2','openai/whisper-large-v3-turbo'):
        own=[r for r in rows if r['model']==name];ok=[r for r in own if r['status']=='ok'];times=sorted(r['ms'] for r in ok)
        summary[name]={'n':len(ok),'errors':len(own)-len(ok),'p50_ms':round(statistics.median(times),3) if times else None,
                       'p95_ms':times[min(len(times)-1,int(len(times)*.95))] if times else None,
                       'normalized_wer':round(sum(r['edits'] for r in ok)/sum(r['words'] for r in ok),4) if ok else None}
    data={'method':'Same 32 synthetic SAPI recordings; local Vosk vs live OpenRouter file ASR; no real microphone. WER uses documented alias normalization and counts numeric formatting differences.','summary':summary,'records':rows}
    target.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary),flush=True)


if __name__=='__main__':main()
