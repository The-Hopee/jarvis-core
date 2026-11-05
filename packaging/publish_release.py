"""Upload a checked private prerelease using existing Git Credential Manager auth."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import requests
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from jarvis import __version__
from jarvis.distribution import verify

def main():
    remote=subprocess.run(['git','remote','get-url','origin'],cwd=root,capture_output=True,text=True,check=True).stdout.strip()
    if remote!='https://github.com/The-Hopee/jarvis-core.git':raise RuntimeError('Unexpected release repository')
    verify(root/'dist/Jarvis')
    import os
    credential=subprocess.run(['git','credential','fill'],input='protocol=https\nhost=github.com\n\n',text=True,capture_output=True,
                              env={**os.environ,'GIT_TERMINAL_PROMPT':'0','GCM_INTERACTIVE':'never'},timeout=30)
    values=dict(line.split('=',1) for line in credential.stdout.splitlines() if '=' in line)
    token=values.get('password')
    if not token:raise RuntimeError('GitHub credential unavailable; no token was printed')
    session=requests.Session();session.headers.update({'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'})
    api='https://api.github.com/repos/The-Hopee/jarvis-core'
    tag='v'+__version__;response=session.get(api+'/releases/tags/'+tag,timeout=20)
    if response.status_code==404:
        response=session.post(api+'/releases',json={'tag_name':tag,'name':'Jarvis '+tag,'prerelease':True,'draft':False,
                                                    'body':(root/'docs/RELEASE_CANDIDATE.md').read_text(encoding='utf-8')},timeout=25)
    if response.status_code not in (200,201):raise RuntimeError('GitHub release API HTTP '+str(response.status_code))
    release=response.json();upload=release['upload_url'].split('{',1)[0]
    if not upload.startswith('https://uploads.github.com/repos/The-Hopee/jarvis-core/'):raise RuntimeError('Unexpected asset upload host')
    assets={a['name']:a for a in release['assets']}
    for path in (root/'dist'/('Jarvis-'+__version__+'-windows-x64.zip'),root/'dist'/('Jarvis-'+__version__+'-windows-x64.zip.sha256')):
        with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        existing=assets.get(path.name)
        if existing:
            if existing.get('digest')=='sha256:'+digest:continue
            raise RuntimeError('Existing asset differs; release files are immutable. Use a new version.')
        print(json.dumps({'uploading':path.name,'bytes':path.stat().st_size}),flush=True)
        with path.open('rb') as stream:
            response=session.post(upload,params={'name':path.name},data=stream,headers={'Content-Type':'application/zip' if path.suffix=='.zip' else 'text/plain'},timeout=(15,240))
        if response.status_code!=201:raise RuntimeError('GitHub asset upload HTTP '+str(response.status_code))
        print(json.dumps({'uploaded':path.name}),flush=True)
    print(json.dumps({'release_url':release['html_url']}));return 0

if __name__=='__main__':raise SystemExit(main())
