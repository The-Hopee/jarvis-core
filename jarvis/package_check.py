"""Read-only runtime diagnostics plus isolated DOCX and codec checks; no network/audio."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
from .config import Settings,USER_DIR

def main():
    import av
    import numpy
    import sounddevice
    import tkinter
    import telethon
    import pymorphy3
    from playwright._impl._driver import compute_driver_executable
    from vosk import Model,KaldiRecognizer,SetLogLevel
    from .documents import Documents
    from .ipc import KernelClient
    settings=Settings.load();SetLogLevel(-1)
    recognition=KaldiRecognizer(Model(str(settings.model_path)),16000)
    recognition.AcceptWaveform(b'\0\0'*1600)
    json.loads(recognition.FinalResult())
    with KernelClient(settings.executable) as kernel:
        native=kernel.call('ping')['result']
        status=kernel.call('system_snapshot',{'checks':['cpu','memory','disk','system'],'top_processes':3})['ok']
    with tempfile.TemporaryDirectory(prefix='jarvis-doc-check-') as temporary:
        root=Path(temporary)
        docs=Documents(replace(settings,document_roots=(root,)),None)
        created=docs.create(text='Hello {{name}}',filename='check.docx',open_after=False)
        filled=docs.fill(created['path'],fields={'name':'Jarvis'},open_after=False)
        text=docs.read(filled['path'])
        document_ok='Jarvis' in json.dumps(text,ensure_ascii=False)
    node,driver=compute_driver_executable()
    report={'native':native,'system_metrics':status,'vosk_loaded':True,'docx_create_fill_read':document_ok,
        'av_mp3_decoder':bool(av.Codec('mp3','r')),'numpy':numpy.__version__,
        'playwright_driver_exists':Path(node).is_file() and Path(driver).is_file(),
        'russian_morphology':pymorphy3.MorphAnalyzer().parse('котами')[0].normal_form=='кот',
        'tkinter_imported':True,'telegram_imported':bool(telethon.__version__),
        'private_key_present':bool(settings.api_key),'voice_reference_present':bool(settings.voice_reference)}
    print(json.dumps(report,ensure_ascii=False,indent=2));return 0

if __name__=='__main__':raise SystemExit(main())
