# Build with the pinned Python/requirements on Windows x64.
from pathlib import Path
from PyInstaller.utils.hooks import collect_all,collect_submodules,copy_metadata
root=Path(SPECPATH).parent
datas=[(str(root/'scripts/windows_speech.ps1'),'scripts'),
       (str(root/'models/vosk-model-small-ru-0.22'),'models/vosk-model-small-ru-0.22')]
binaries=[(str(root/'build/bin/Release/jarvis-core.exe'),'build/bin/Release'),
          (str(root/'build/bin/Release/jarvis_core.dll'),'build/bin/Release')]
hidden=collect_submodules('jarvis')
for package in ('vosk','sounddevice','av','playwright','pymorphy3','pymorphy3_dicts_ru'):
    data,libs,imports=collect_all(package)
    datas+=data;binaries+=libs;hidden+=imports
for package in ('vosk','sounddevice','edge-tts','jsonschema','av','telethon','playwright','pymorphy3'):
    datas+=copy_metadata(package)
a=Analysis([str(root/'packaging/frozen_entry.py')],pathex=[str(root)],binaries=binaries,datas=datas,
           hiddenimports=hidden,excludes=['torch','torchaudio','scipy','pandas','matplotlib','IPython','pytest','PyQt5','PySide6'])
pyz=PYZ(a.pure)
console=EXE(pyz,a.scripts,[],exclude_binaries=True,name='Jarvis',console=True,upx=False,manifest=str(root/'packaging/windows.manifest'))
panel=EXE(pyz,a.scripts,[],exclude_binaries=True,name='JarvisPanel',console=False,upx=False,manifest=str(root/'packaging/windows.manifest'))
bundle=COLLECT(console,panel,a.binaries,a.datas,name='Jarvis',upx=False)
