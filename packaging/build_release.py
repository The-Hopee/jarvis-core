"""Create a checked, secret-free immutable package and SHA256 archive."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from jarvis import __version__
from jarvis.distribution import verify

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--skip-build',action='store_true');args=parser.parse_args()
    if not args.skip_build:
        subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--distpath',str(root/'dist'),
                        '--workpath',str(root/'build/frozen'),str(root/'packaging/Jarvis.spec')],cwd=root,check=True)
    source=root/'dist/Jarvis'
    for name in ('manifest.json','РУКОВОДСТВО.html','ПРОВЕРКА-УСТАНОВКИ.md'):
        (source/name).unlink(missing_ok=True)
    shutil.copyfile(root/'docs/USER_GUIDE.html',source/'РУКОВОДСТВО.html')
    shutil.copyfile(root/'docs/PILOT_CHECKLIST.md',source/'ПРОВЕРКА-УСТАНОВКИ.md')
    shutil.copyfile(root/'docs/PRIVACY.md',source/'ПРИВАТНОСТЬ.md')
    shutil.copyfile(root/'packaging/checks-python.json',source/'checks-python.json')
    shutil.copyfile(root/'packaging/THIRD_PARTY_NOTICES.txt',source/'THIRD_PARTY_NOTICES.txt')
    python_license=Path(sys.base_prefix)/'LICENSE.txt'
    if python_license.is_file():shutil.copyfile(python_license,source/'PYTHON-LICENSE.txt')
    # Only enumerated application/runtime data from Analysis is included. Never copy repo root.
    banned={'.env','settings.env','agent.py','projects.json','jobs.sqlite','budgets.sqlite'}
    paths=sorted(p for p in source.rglob('*') if p.is_file())
    for path in paths:
        if path.name in banned or path.suffix in {'.session','.log'}:raise RuntimeError('Private file in build: '+str(path.relative_to(source)))
    files={}
    for path in paths:
        with path.open('rb') as stream:files[path.relative_to(source).as_posix()]=hashlib.file_digest(stream,'sha256').hexdigest()
    (source/'manifest.json').write_text(json.dumps({'version':__version__,'platform':'windows-x64','python':sys.version.split()[0],
        'pyinstaller':importlib.metadata.version('pyinstaller'),'files':files},ensure_ascii=False,indent=2),encoding='utf-8')
    verify(source)
    archive=root/'dist'/('Jarvis-'+__version__+'-windows-x64.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as out:
        for path in sorted(source.rglob('*')):
            if path.is_file():out.write(path,'Jarvis/'+path.relative_to(source).as_posix())
    with archive.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    archive.with_suffix('.zip.sha256').write_text(digest+'  '+archive.name+'\n',encoding='ascii')
    print(json.dumps({'archive':str(archive),'bytes':archive.stat().st_size,'unpacked_bytes':sum(p.stat().st_size for p in source.rglob('*') if p.is_file()),'files':len(files),'sha256':digest},indent=2))

if __name__=='__main__':main()
