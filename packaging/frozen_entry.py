"""Explicit allowlist for subprocess dispatch; never execute arbitrary module names."""
import multiprocessing
from pathlib import Path
import sys

def main():
    multiprocessing.freeze_support()
    if '--self-test' in sys.argv:
        from jarvis.package_check import main
        return main()
    if '--ui-smoke' in sys.argv:
        from jarvis.desktop_ui import main
        return main(smoke=True)
    if len(sys.argv)>2 and sys.argv[1]=='--internal':
        name=sys.argv[2];sys.argv=[sys.argv[0],*sys.argv[3:]]
        if name=='vk_worker':
            from jarvis.vk_worker import main
        elif name=='coding_worker':
            from jarvis.coding_worker import main
        elif name=='coding':
            from jarvis.coding import main
        elif name=='control':
            from jarvis.control import main
        elif name=='background':
            from jarvis.background import main
        elif name=='playwright':
            from playwright.__main__ import main
        else:raise SystemExit('Unknown internal entry point')
        return main()
    if '--background' in sys.argv:
        sys.argv=[sys.argv[0]]
        from jarvis.background import main
        return main()
    if '--ui' in sys.argv or (len(sys.argv)==1 and Path(sys.executable).stem=='JarvisPanel'):
        from jarvis.desktop_ui import main
        return main()
    from jarvis.__main__ import main
    return main()

if __name__=='__main__':raise SystemExit(main())
