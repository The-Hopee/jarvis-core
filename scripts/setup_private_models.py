"""Download pinned local-only model/runtime files; never upload account data."""
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
import zipfile
import requests

BASE=Path(os.environ['LOCALAPPDATA'])/'Jarvis'
TAG='b12110'
TEXT_REPO='unsloth/Qwen3.5-4B-GGUF'
TTS_REPO='Qwen/Qwen3-TTS-12Hz-0.6B-Base'
TEXT_FILE='Qwen3.5-4B-Q4_K_M.gguf'
REVISIONS={TEXT_REPO:'e87f176479d0855a907a41277aca2f8ee7a09523',
           TTS_REPO:'5d83992436eae1d760afd27aff78a71d676296fc'}


def fetch_json(url):
    r=requests.get(url,timeout=40);r.raise_for_status();return r.json()


def download(item):
    path=Path(item['path']);path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_file() and path.stat().st_size==item['size']:
        with path.open('rb') as source:digest=hashlib.file_digest(source,'sha256').hexdigest()
        if digest==item['sha256']:return
    part=path.with_suffix(path.suffix+'.part')
    for attempt in range(5):
        try:
            offset=part.stat().st_size if part.exists() else 0
            headers={'Range':f'bytes={offset}-'} if offset else {}
            with requests.get(item['url'],headers=headers,stream=True,timeout=(30,60)) as response:
                response.raise_for_status()
                if response.status_code!=206:offset=0
                total=offset;last=offset
                with part.open('ab' if offset else 'wb') as target:
                    for chunk in response.iter_content(4*1024*1024):
                        total+=len(chunk)
                        if total>item['size']:raise RuntimeError('Download exceeds pinned file size')
                        target.write(chunk)
                        if total-last>=128*1024*1024:
                            print(json.dumps({'download':path.name,'MiB':total//(1024**2),'total_MiB':item['size']//(1024**2)}),flush=True);last=total
            with part.open('rb') as source:digest=hashlib.file_digest(source,'sha256').hexdigest()
            if part.stat().st_size!=item['size'] or digest!=item['sha256']:
                part.unlink(missing_ok=True);raise RuntimeError('Downloaded file failed size/SHA256 verification')
            part.replace(path);print(json.dumps({'verified':path.name}),flush=True);return
        except (requests.RequestException,OSError,RuntimeError):
            if attempt==4:raise
            time.sleep(min(2**attempt,10))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-only',action='store_true',help='verify installed files offline, without downloads')
    args=parser.parse_args()
    if args.verify_only:
        manifest=json.loads((BASE/'local-model-install.json').read_text(encoding='utf-8'))
        for item in manifest['files']:
            path=Path(item['path'])
            with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
            if path.stat().st_size!=item['size'] or digest!=item['sha256']:raise RuntimeError('Installed file failed integrity verification')
        print(json.dumps({'verified':True,'files':len(manifest['files']),'network_requests':0}));return
    cache=BASE/'downloads/private-models';items=[];revisions={}
    for repo,folder,only in ((TEXT_REPO,BASE/'models/local-text',{TEXT_FILE}),
                             (TTS_REPO,BASE/'models/local-voice',None)):
        revision=REVISIONS[repo];revisions[repo]=revision
        files=fetch_json('https://huggingface.co/api/models/'+repo+'/tree/'+revision+'?recursive=true')
        for f in files:
            name=f['path']
            if f['type']!='file' or (only and name not in only):continue
            if not only and not name.endswith(('.safetensors','.json','.txt')):continue
            if name=='README.md' or name.startswith('.') or '..' in Path(name).parts:continue
            digest=f.get('lfs',{}).get('oid')
            url='https://huggingface.co/'+repo+'/resolve/'+revision+'/'+name
            if not digest:
                r=requests.get(url,timeout=40);r.raise_for_status();digest=hashlib.sha256(r.content).hexdigest()
            items.append({'url':url,'size':f['size'],'sha256':digest,'path':str(folder/name)})
    release=fetch_json('https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/'+TAG)
    archives=[]
    for name in ('llama-'+TAG+'-bin-win-cuda-12.4-x64.zip','cudart-llama-bin-win-cuda-12.4-x64.zip'):
        asset=next(a for a in release['assets'] if a['name']==name)
        archives.append(cache/name)
        items.append({'url':asset['browser_download_url'],'size':asset['size'],
                      'sha256':asset['digest'].removeprefix('sha256:'),'path':str(cache/name)})
    needed=sum(i['size'] for i in items if not Path(i['path']).exists())+5*1024**3
    if shutil.disk_usage(BASE).free<needed:raise RuntimeError('Not enough free disk space for local model installation')
    with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(download,items))
    runtime=BASE/'runtimes'/('llama-'+TAG);runtime.mkdir(parents=True,exist_ok=True)
    for archive in archives:
        with zipfile.ZipFile(archive) as z:
            for member in z.infolist():
                target=(runtime/member.filename).resolve()
                if not target.is_relative_to(runtime.resolve()):raise RuntimeError('Runtime archive path escapes destination')
            z.extractall(runtime)
    executable=next(runtime.rglob('llama-server.exe'))
    manifest={'schema':1,'revisions':revisions,'llama_version':TAG,'files':items,
              'llama_executable':str(executable),'text_model':str(BASE/'models/local-text'/TEXT_FILE),
              'voice_model':str(BASE/'models/local-voice'),
              'voice_python':str(BASE/'runtimes/qwen-tts/Scripts/python.exe')}
    (BASE/'local-model-install.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps({'installed':True,'files':len(items),'model_bytes':sum(i['size'] for i in items)}),flush=True)


if __name__=='__main__':main()
