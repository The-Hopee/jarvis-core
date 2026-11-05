"""Live network lookups and isolated document round trip; no voice or messages."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from jarvis.config import Settings,USER_DIR
from jarvis.ipc import KernelClient
from jarvis.setup import ensure_native_config
from jarvis.services import LocalServices
from jarvis.media import YouTube
from jarvis.documents import Documents

def main():
    settings=Settings.load();report={}
    with KernelClient(settings.executable,ensure_native_config(settings)) as kernel:
        services=LocalServices(settings,kernel);youtube=YouTube(kernel)
        with ThreadPoolExecutor(max_workers=2) as pool:
            weather=pool.submit(services.weather);videos=pool.submit(youtube.search,'Егор Крид',2)
            for name,future in [('weather',weather),('youtube',videos)]:
                try:
                    value=future.result()
                    report[name]={'ok':True,'source':value.get('source'),'results':len(value.get('videos',[]))} if name=='youtube' else {'ok':True,'source':value['source'],'source_time':value['current'].get('time'),'configured_city_used':value['location'].get('source')=='configured_city'}
                except Exception as exc:report[name]={'ok':False,'error':str(exc)[:160]}
        with tempfile.TemporaryDirectory(prefix='jarvis-home-doc-') as temporary:
            docs=Documents(replace(settings,document_roots=(Path(temporary),)),kernel)
            source=docs.create('Имя: {{name}}',filename='template.docx',open_after=False)
            filled=docs.fill(source['path'],fields={'name':'Jarvis'},open_after=False)
            original=docs.read(source['path']);copy=docs.read(filled['path'])
            report['documents']={'source_preserved':'{{name}}' in json.dumps(original,ensure_ascii=False),
                                 'copy_filled':'Jarvis' in json.dumps(copy,ensure_ascii=False)}
    (USER_DIR/'benchmarks/stage09-services.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))

if __name__=='__main__':main()
