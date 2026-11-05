"""Versioned per-user installs, verified files, retained previous version."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from .config import USER_DIR
from .http import ServiceError

INSTALL_ROOT=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'Programs/Jarvis'
OWNER_TEXT='Jarvis managed installation directory v1\n'

def owned(root):
    try:return (Path(root)/'.jarvis-owner').read_text(encoding='utf-8')==OWNER_TEXT
    except OSError:return False

def write_json(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(path)

def read_state(root=INSTALL_ROOT):
    try:return json.loads((root/'installation.json').read_text(encoding='utf-8'))
    except FileNotFoundError:return {}

def verify(source):
    source=Path(source).resolve()
    manifest=json.loads((source/'manifest.json').read_text(encoding='utf-8'))
    version=manifest.get('version','')
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:-rc\.\d+)?',version):raise ServiceError('Некорректная версия пакета')
    files=manifest.get('files',{})
    if not isinstance(files,dict) or not {'Jarvis.exe','JarvisPanel.exe'}<=files.keys():raise ServiceError('Неполный установочный пакет')
    actual={p.relative_to(source).as_posix() for p in source.rglob('*') if p.is_file()}
    if actual!=set(files)|{'manifest.json'}:raise ServiceError('Состав пакета не совпадает с manifest.json')
    for name,digest in files.items():
        relative=Path(name)
        if relative.is_absolute() or '..' in relative.parts or ':' in name or name.startswith(('/', '\\')):raise ServiceError('Недопустимый путь в пакете')
        path=source/relative
        if path.is_symlink() or path.is_junction() or not path.resolve().is_relative_to(source):raise ServiceError('Ссылки в пакете запрещены')
        with path.open('rb') as stream:actual_digest=hashlib.file_digest(stream,'sha256').hexdigest()
        if actual_digest!=digest:raise ServiceError('Контрольная сумма не совпала: '+name)
    return manifest

def version_path(root,version):
    if not isinstance(version,str) or not re.fullmatch(r'\d+\.\d+\.\d+(?:-rc\.\d+)?',version):raise ServiceError('Некорректная версия установки')
    root=Path(root).resolve();path=(root/'versions'/version).resolve()
    if not path.is_relative_to(root/'versions'):raise ServiceError('Путь выходит за каталог программы')
    return path

def shortcuts(target,autostart,*,remove=False):
    """Shell shortcuts, current Windows user only; no admin or credentials."""
    appdata=Path(os.environ['APPDATA']);desktop=Path.home()/'Desktop'
    # Windows may redirect Desktop to OneDrive; ask the OS rather than guessing.
    script=r'''
$ErrorActionPreference='Stop'
$p=Get-Content -Raw -LiteralPath $env:JARVIS_SHORTCUT_SPEC | ConvertFrom-Json
$shell=New-Object -ComObject WScript.Shell
$desktop=$shell.SpecialFolders.Item('Desktop')
$items=@(@{Path=(Join-Path $desktop 'Jarvis.lnk');Args='--ui';Enabled=(!$p.remove)},
 @{Path=(Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Jarvis.lnk');Args='--ui';Enabled=(!$p.remove)},
 @{Path=(Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup\Jarvis.lnk');Args='--background';Enabled=(!$p.remove -and $p.autostart)})
foreach($item in $items){
 if($item.Enabled){$s=$shell.CreateShortcut($item.Path);$s.TargetPath=$p.target;$s.Arguments=$item.Args;$s.WorkingDirectory=$p.directory;$s.WindowStyle=7;$s.Description='Jarvis home assistant';$s.Save()}
 elseif(Test-Path -LiteralPath $item.Path){Remove-Item -LiteralPath $item.Path}
}
'''
    with tempfile.TemporaryDirectory(prefix='jarvis-shortcuts-') as temporary:
        spec=Path(temporary)/'shortcuts.json';spec.write_text(json.dumps({'target':str(target/'JarvisPanel.exe'),'directory':str(target),'autostart':autostart,'remove':remove}),encoding='utf-8')
        env={**os.environ,'JARVIS_SHORTCUT_SPEC':str(spec)}
        completed=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],env=env,capture_output=True,timeout=20,
                                  creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if completed.returncode:raise ServiceError('Не удалось создать ярлыки Windows')

def install(source,*,root=INSTALL_ROOT,create_shortcuts=True):
    source=Path(source).resolve();root=Path(root).resolve();manifest=verify(source)
    if root.exists() and any(root.iterdir()) and not owned(root):raise ServiceError('Каталог занят другой программой; установка остановлена')
    root.mkdir(parents=True,exist_ok=True)
    (root/'.jarvis-owner').write_text(OWNER_TEXT,encoding='utf-8')
    target=version_path(root,manifest['version'])
    state=read_state(root)
    if target.exists():
        installed=verify(target)
        if installed!=manifest:raise ServiceError('Такая версия уже установлена с другим содержимым; используйте новый номер версии')
    else:
        target.parent.mkdir(parents=True,exist_ok=True)
        temporary=target.with_name(target.name+'.staging')
        if temporary.exists():
            resolved=temporary.resolve()
            if temporary.is_symlink() or temporary.is_junction() or resolved.parent!=target.parent.resolve() or resolved.name!=target.name+'.staging':
                raise ServiceError('Неожиданный путь незавершённой установки')
            shutil.rmtree(resolved)
        shutil.copytree(source,temporary);verify(temporary);temporary.rename(target)
    previous=state.get('current') if state.get('current')!=manifest['version'] else state.get('previous')
    if create_shortcuts:shortcuts(target,state.get('autostart',False))
    write_json(root/'installation.json',{'current':manifest['version'],'previous':previous,'autostart':state.get('autostart',False)})
    return target

def rollback(*,root=INSTALL_ROOT,create_shortcuts=True):
    root=Path(root).resolve();state=read_state(root)
    if not state.get('previous'):raise ServiceError('Предыдущей версии пока нет')
    target=version_path(root,state['previous']);verify(target)
    if create_shortcuts:shortcuts(target,state.get('autostart',False))
    write_json(root/'installation.json',{**state,'current':state['previous'],'previous':state['current']})
    return target

def set_autostart(enabled,*,root=INSTALL_ROOT):
    state=read_state(root)
    if not state.get('current'):raise ServiceError('Сначала установите программу')
    target=version_path(root,state['current']);verify(target);shortcuts(target,bool(enabled))
    write_json(Path(root)/'installation.json',{**state,'autostart':bool(enabled)})

def uninstall_script(*,root=INSTALL_ROOT,erase_data=False,remove_shortcuts=True):
    """Only emit deletion after validating both absolute target boundaries."""
    root=Path(root).resolve();expected=INSTALL_ROOT.resolve()
    if INSTALL_ROOT.is_symlink() or INSTALL_ROOT.is_junction() or root!=expected or root.name!='Jarvis' or root.parent!=(Path(os.environ['LOCALAPPDATA'])/'Programs').resolve():raise ServiceError('Неожиданный путь установки; удаление остановлено')
    if not owned(root):raise ServiceError('Каталог не принадлежит установщику Jarvis')
    if not read_state(root).get('current'):raise ServiceError('Установка не найдена')
    if USER_DIR==root or USER_DIR.is_relative_to(root) or root.is_relative_to(USER_DIR):raise ServiceError('Каталоги программы и данных пересекаются')
    if erase_data and USER_DIR!=(Path(os.environ['LOCALAPPDATA'])/'Jarvis').resolve():raise ServiceError('Удаление нестандартного каталога данных через установщик запрещено')
    raw_data=Path(os.environ['LOCALAPPDATA'])/'Jarvis'
    if erase_data and (raw_data.is_junction() or raw_data.is_symlink()):raise ServiceError('Удаление данных через ссылку запрещено')
    if remove_shortcuts:shortcuts(version_path(root,read_state(root)['current']),False,remove=True)
    # The helper waits for the panel to close, then removes exactly these literals.
    quoted=lambda p:"'"+str(p).replace("'","''")+"'"
    script='Start-Sleep -Seconds 4\nRemove-Item -LiteralPath '+quoted(root)+' -Recurse -Force\n'
    if erase_data:script+='Remove-Item -LiteralPath '+quoted(USER_DIR)+' -Recurse -Force\n'
    handle,path=tempfile.mkstemp(prefix='jarvis-uninstall-',suffix='.ps1');os.close(handle)
    Path(path).write_text(script,encoding='utf-8-sig')
    return path
