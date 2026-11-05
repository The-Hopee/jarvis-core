"""Same module protocol in source checkouts and frozen Windows distributions."""
from pathlib import Path
import sys

MODULES={'jarvis.vk_worker','jarvis.coding_worker','jarvis.coding','jarvis.control','jarvis.background','playwright'}

def command(module,*arguments):
    if module not in MODULES:raise ValueError('Unsupported child module')
    executable=sys.executable.replace('pythonw.exe','python.exe')
    if getattr(sys,'frozen',False):
        executable=str(Path(sys.executable).with_name('Jarvis.exe'))
        return [executable,'--internal',module.removeprefix('jarvis.'),*map(str,arguments)]
    return [executable,'-m',module,*map(str,arguments)]
