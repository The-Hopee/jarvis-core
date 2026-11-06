"""Offline Qwen TTS in its separate Python environment; UTF-8 stdio IPC only."""
import argparse
import contextlib
import json
import os
from pathlib import Path
import socket
import sys

# The worker is launched by filename in its separate environment. Do not let
# jarvis/http.py shadow the standard-library http package used by model imports.
sys.path=[entry for entry in sys.path if Path(entry or '.').resolve()!=Path(__file__).parent.resolve()]


def block_network(*_args,**_kwargs):raise OSError('Network disabled in local voice worker')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--model',required=True);args=parser.parse_args()
    sys.stdin.reconfigure(encoding='utf-8');sys.stdout.reconfigure(encoding='utf-8');sys.stderr.reconfigure(encoding='utf-8')
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',
                      DO_NOT_TRACK='1',GRADIO_ANALYTICS_ENABLED='False')
    if os.environ.get('JARVIS_LOCAL_DIAGNOSTICS')=='1':
        import faulthandler
        faulthandler.dump_traceback_later(45,repeat=True,file=sys.stderr)
    socket.socket.connect=block_network;socket.socket.connect_ex=block_network
    socket.socket.sendto=block_network;socket.create_connection=block_network
    model=None;prompt=None;reference_key=None
    for raw in sys.stdin:
        request={}
        try:
            if len(raw)>128*1024:raise ValueError('oversize')
            request=json.loads(raw)
            if request.get('method')=='privacy_probe':
                blocked=False
                if socket.socket.connect is block_network:
                    try:
                        with socket.socket() as probe:probe.connect(('203.0.113.1',443))
                    except OSError:blocked=True
                print(json.dumps({'protocol_version':1,'id':request['id'],'ok':True,'result':{'network_blocked':blocked}}),flush=True)
                continue
            if request.get('method')!='synthesize':raise ValueError('unknown method')
            data=request['params'];text=data['text'];path=Path(data['path']).resolve();reference=Path(data['reference']).resolve()
            if not isinstance(text,str) or not 0<len(text)<=2400:raise ValueError('text size')
            if not reference.is_file() or reference.stat().st_size>10*1024*1024 or reference.suffix.lower() not in {'.wav','.mp3'}:raise ValueError('reference')
            if path.suffix.lower()!='.wav' or not path.parent.is_dir() or path.exists():raise ValueError('output')
            with contextlib.redirect_stdout(sys.stderr):
                if model is None:
                    print('[local-voice] import',file=sys.stderr,flush=True)
                    import torch
                    import soundfile as sf
                    from qwen_tts import Qwen3TTSModel
                    torch.set_num_threads(4)
                    if not torch.cuda.is_available():raise RuntimeError('CUDA unavailable')
                    if not torch.cuda.is_bf16_supported():raise RuntimeError('BF16 GPU required for this local voice')
                    print('[local-voice] load',file=sys.stderr,flush=True)
                    model=Qwen3TTSModel.from_pretrained(args.model,device_map='cuda:0',dtype=torch.bfloat16,
                                                     attn_implementation='sdpa',local_files_only=True)
                    print('[local-voice] loaded',file=sys.stderr,flush=True)
                key=(str(reference),reference.stat().st_mtime_ns,data['reference_text'])
                if key!=reference_key:
                    print('[local-voice] clone',file=sys.stderr,flush=True)
                    prompt=model.create_voice_clone_prompt(ref_audio=str(reference),ref_text=data['reference_text'])
                    reference_key=key
                print('[local-voice] generate',file=sys.stderr,flush=True)
                wavs,rate=model.generate_voice_clone(text=text,language='Russian',voice_clone_prompt=prompt,
                                                     max_new_tokens=600,do_sample=True,temperature=.7,top_p=.95,
                                                     repetition_penalty=1.05)
                sf.write(str(path),wavs[0],rate)
                print('[local-voice] written',file=sys.stderr,flush=True)
            result={'protocol_version':1,'id':request['id'],'ok':True,'result':{'written':True,'sample_rate':rate}}
        except Exception as exc:
            # Neither dictated text nor model tracebacks belong in the IPC error.
            result={'protocol_version':1,'id':request.get('id'),'ok':False,
                    'error':{'code':'local_voice_error','message':'Offline voice error: '+type(exc).__name__}}
        print(json.dumps(result),flush=True)


if __name__=='__main__':main()
