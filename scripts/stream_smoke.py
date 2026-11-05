"""Live model and voice, simulated output sink: no audible speech or app launch."""
from pathlib import Path
import json
import sys
import time
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from jarvis.config import Settings,USER_DIR
from jarvis.assistant import Assistant
from jarvis.interaction import run_turn
from jarvis.ipc import KernelClient
from jarvis.openrouter import OpenRouterClient
from jarvis.speech import Speaker
from jarvis.telemetry import TurnTrace
from scripts.latency_benchmark import registry


class SilentOutput:
    def __init__(self,**kwargs):pass
    def __enter__(self):return self
    def write(self,pcm):time.sleep(len(pcm)/48000)
    def abort(self):pass
    def __exit__(self,*_):pass


def main():
    settings=Settings.load();records=[]
    with KernelClient(settings.executable) as kernel,patch('sounddevice.RawOutputStream',SilentOutput):
        for text in ('Привет.','Открой VS Code.'):
            tools=registry(settings,kernel)
            trace=TurnTrace('stream_silent_smoke',sink=records.append)
            assistant=Assistant(tools,OpenRouterClient(settings.api_key,settings.model))
            from jarvis.progress import ProgressFeedback
            run_turn(assistant,Speaker(settings),text,trace=trace,feedback=ProgressFeedback(Speaker(settings),enabled=False))
            tools.close()
    for r in records:r['playback_is_virtual']=True
    target=USER_DIR/'benchmarks/stage06-stream-smoke.json'
    target.write_text(json.dumps(records,indent=2),encoding='utf-8')
    print(json.dumps([{'status':r['status'],'events':r['events_ms']} for r in records]),flush=True)


if __name__=='__main__':main()
