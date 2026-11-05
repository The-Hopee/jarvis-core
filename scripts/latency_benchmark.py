"""Explicit paid benchmark: synthetic WAV replay, real ASR/LLM/TTS, fixture actions.

No microphone, live chats, browser profile, app launch or message sending.
Replays 32 warm cases and the same first four with fresh local model/processes.
"""
from collections import deque
from contextlib import ExitStack
from dataclasses import replace
import argparse
import json
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch
import wave

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from jarvis.assistant import Assistant
from jarvis.config import Settings, USER_DIR
from jarvis.interaction import run_turn
from jarvis.ipc import KernelClient
from jarvis.openrouter import OpenRouterClient
from jarvis.progress import ProgressFeedback
from jarvis.services import LocalServices
from jarvis.speech import Speaker, windows_speak
from jarvis.telemetry import append_record, report, mark
from jarvis.tools import ToolRegistry, Tool
from jarvis.voice import VoiceInput, WakeGate

CASES = [
    'Джарвис, состояние машины.', 'Джарвис, сколько свободной памяти?',
    'Джарвис, как загружен процессор?', 'Джарвис, проверь состояние компьютера.',
    'Джарвис, какая погода?', 'Джарвис, какая температура на улице?',
    'Джарвис, холодно ли сегодня?', 'Джарвис, сколько градусов в Дзержинске?',
    'Джарвис, открой VS Code.', 'Джарвис, открой телеграм.',
    'Джарвис, открой калькулятор.', 'Джарвис, открой блокнот.',
    'Джарвис, открой ютуб.', 'Джарвис, открой сайт example.com.',
    'Джарвис, открой яндекс.', 'Джарвис, открой гугл.',
    'Джарвис, привет.', 'Джарвис, я дома.',
    'Джарвис, чем займёмся сегодня?', 'Джарвис, ты на связи?',
    'Джарвис, сколько будет семь умножить на восемь?', 'Джарвис, сколько минут в двух часах?',
    'Джарвис, сколько будет пятнадцать процентов от двухсот?', 'Джарвис, сколько метров в километре?',
    'Джарвис, объясни одним предложением, что такое переменная.',
    'Джарвис, объясни коротко, зачем нужны тесты.',
    'Джарвис, чем список отличается от словаря в Python? Ответь кратко.',
    'Джарвис, что такое оперативная память? Ответь коротко.',
    'Джарвис, спасибо.', 'Джарвис, благодарю.',
    'Джарвис, напомни, что ты умеешь, в двух предложениях.',
    'Джарвис, предложи одно занятие на вечер.'
]


class SilentSpeaker(Speaker):
    """Render through the real provider, but never claim playback occurred."""
    def _play_file(self, path, *, before_playback=None, status=False, relevant=None):
        if before_playback:
            before_playback()
        mark('playback_skipped')
        return True


class Replay:
    def __init__(self, pcm, sample_rate, done):
        self.pcm, self.rate, self.done = pcm, sample_rate, done
        self.stop = threading.Event()

    def factory(self, **kwargs):
        self.callback=kwargs['callback']
        return self

    def __enter__(self):
        def feed():
            block=self.rate//5*2
            for start in range(0,len(self.pcm),block):
                data=self.pcm[start:start+block]
                duration=len(data)/(self.rate*2)
                if self.stop.wait(duration):
                    return
                now=time.monotonic()
                self.callback(data,len(data)//2,SimpleNamespace(currentTime=now,inputBufferAdcTime=now-duration),None)
            self.done.set()
        self.thread=threading.Thread(target=feed,daemon=True)
        self.thread.start()
        return self

    def __exit__(self,*_):
        self.stop.set();self.thread.join(timeout=2)


def registry(settings,kernel):
    tools=ToolRegistry(kernel,LocalServices(settings,kernel))
    keep={'get_system_status','get_weather','open_application','open_website'}
    tools.tools={name:tool for name,tool in tools.tools.items() if name in keep}
    weather={'location':{'city':'Дзержинск','source':'configured_city'},
             'current':{'temperature_2m':5,'apparent_temperature':3},'fixture':True}
    for name in ('get_weather','open_application','open_website'):
        old=tools.tools[name]
        def fixture(_name=name,**args):
            if _name=='get_weather':
                return weather
            return {'status':'shell_accepted','app_id':args.get('app_id'),'benchmark_fixture':True}
        tools.tools[name]=Tool(old.name,old.description,old.parameters,fixture)
    return tools


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true',help='required: consent to paid ASR/LLM/TTS calls and audible test responses')
    parser.add_argument('--count',type=int,default=32)
    parser.add_argument('--cold',type=int,default=4)
    parser.add_argument('--mode',choices=('both','warm','cold'),default='both')
    parser.add_argument('--silent',action='store_true',help='synthesize responses without playing them; playback metrics are omitted')
    parser.add_argument('--virtual-output',action='store_true',help='stream into a realtime silent PCM sink; dispatch timings are virtual')
    parser.add_argument('--output',type=Path,default=USER_DIR/'benchmarks/stage05')
    args=parser.parse_args()
    if not args.live or not 1<=args.count<=len(CASES) or not 0<=args.cold<=args.count:
        parser.error('Use --live, count 1..32, cold 0..count. No private accounts are exercised.')
    sys.stdout.reconfigure(encoding='utf-8')
    virtual_patch=None
    if args.virtual_output:
        from scripts.stream_smoke import SilentOutput
        virtual_patch=patch('sounddevice.RawOutputStream',SilentOutput)
    import vosk
    vosk.SetLogLevel(-1)
    settings=Settings.load()
    if args.silent:
        settings=replace(settings,tts_streaming=False)
    if not settings.api_key:
        parser.error('OpenRouter is not configured')
    args.output.mkdir(parents=True,exist_ok=True)
    audio_dir=args.output/'synthetic-inputs';audio_dir.mkdir(exist_ok=True)
    for index,text in enumerate(CASES[:args.count]):
        path=audio_dir/f'{index+1:02}.wav'
        if not path.is_file():
            windows_speak(text,path)
        print(f'prepared {index+1}/{args.count}',flush=True)
    log=args.output/'timings.jsonl'
    if log.exists():
        parser.error('Choose a fresh output directory; previous measurements are preserved.')
    outcomes=[]
    with ExitStack() as resources:
        if virtual_patch:resources.enter_context(virtual_patch)
        initial=time.monotonic()
        kernel=resources.enter_context(KernelClient(settings.executable))
        model=vosk.Model(str(settings.model_path))
        speaker_class=SilentSpeaker if args.silent else Speaker
        speaker=speaker_class(settings)
        init_ms=round((time.monotonic()-initial)*1000,3)
        rounds=([('warm',i) for i in range(args.count)] if args.mode!='cold' else [])+([('cold',i) for i in range(args.cold)] if args.mode!='warm' else [])
        for mode,index in rounds:
            started=time.monotonic()
            cold_kernel=None
            try:
                if mode=='cold':
                    cold_kernel=KernelClient(settings.executable)
                    active_kernel=cold_kernel
                    active_model=vosk.Model(str(settings.model_path))
                    active_speaker=speaker_class(settings)
                else:
                    active_kernel,active_model,active_speaker=kernel,model,speaker
                startup_ms=round((time.monotonic()-started)*1000,3) if mode=='cold' else init_ms if index==0 else 0
                tools=registry(settings,active_kernel)
                agent=Assistant(tools,OpenRouterClient(settings.api_key,settings.model))
                with wave.open(str(audio_dir/f'{index+1:02}.wav'),'rb') as audio:
                    rate=audio.getframerate();pcm=audio.readframes(audio.getnframes())+b'\0\0'*(rate*2)
                done=threading.Event();replay=Replay(pcm,rate,done)
                voice=VoiceInput.__new__(VoiceInput)
                voice.model,voice.sample_rate,voice.device=active_model,rate,None
                voice.settings,voice.cloud_retry_at,voice.last_trace=settings,0,None
                voice.gate,voice.messages=WakeGate(),deque(maxlen=5)
                voice.gate.resume(120)
                feedback=ProgressFeedback(active_speaker,delay=settings.progress_delay,enabled=not args.silent and not args.virtual_output)
                def accepted(trace):
                    trace.source='benchmark_'+mode
                    trace.sink=lambda row:append_record({**row,'case_id':index+1,'startup_ms':startup_ms,'playback_is_virtual':args.virtual_output},log)
                try:
                    with patch('sounddevice.RawInputStream',replay.factory):
                        text=voice.next_command(stop_requested=done.is_set,on_accepted=accepted)
                    if text is None:
                        outcomes.append({'mode':mode,'case_id':index+1,'status':'endpoint_failed'})
                        print(f'{mode} {index+1}: endpoint_failed',flush=True)
                        continue
                    result=run_turn(agent,active_speaker,text,trace=voice.last_trace,feedback=feedback)
                    summary={'mode':mode,'case_id':index+1,'status':'degraded' if result.warning else 'completed',
                             'reply_chars':len(result.text),'tool_calls':len(result.tools),'startup_ms':startup_ms,
                             'expected_synthetic_text':CASES[index],'recognized_synthetic_text':text}
                    outcomes.append(summary)
                    print(json.dumps({k:v for k,v in summary.items() if not k.endswith('_text')}),flush=True)
                finally:
                    feedback.stop()
                    tools.close()
                    if voice.last_trace is not None:
                        voice.last_trace.finish('error')
            finally:
                if cold_kernel:
                    cold_kernel.close()
    results={'method':'synthetic WAV replay at realtime speed; live ASR/LLM/TTS; system probe real; all other actions fixtures; no microphone or chats',
             'playback':not args.silent,
             'playback_is_virtual':args.virtual_output,
             'warm':report([log],source='benchmark_warm'),'cold':report([log],source='benchmark_cold'),
             'outcomes':outcomes}
    (args.output/'report.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'report':str(args.output/'report.json'),'completed':sum(r['status']=='completed' for r in outcomes),'total':len(outcomes)}),flush=True)
    return 0 if all(r['status']=='completed' for r in outcomes) else 1


if __name__=='__main__':
    raise SystemExit(main())
