"""Export only non-sensitive acceptance metadata, after running release checks."""
import json
from pathlib import Path
import sys
import re
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from jarvis.config import ROOT,USER_DIR

def main():
    test_log=(ROOT/'build/tests-publish.log').read_bytes()
    log_text=test_log.decode('utf-16' if test_log.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8',errors='replace')
    matches=re.findall(r'Ran\s+(\d+)\s+tests',log_text)
    if not matches:raise RuntimeError('Final test report not found')
    test_count=int(matches[-1])
    records={}
    for name in ('stage09-services','stage09-vk-lookup','stage11-package-smoke','stage11-frozen-coding-smoke','stage11-private-vk-smoke'):
        record=json.loads((USER_DIR/'benchmarks'/(name+'.json')).read_text(encoding='utf-8'))
        if 'budget' in record:
            record['budget']={k:round(v,10) for k,v in record['budget'].items()}
        records[name]=record
    (ROOT/'docs/benchmarks/stage11-2026-11-05.json').write_text(json.dumps(records,indent=2)+'\n',encoding='utf-8')
    with (ROOT/'docs/VALIDATION.md').open('a',encoding='utf-8') as f:
        f.write('\n## 2026-11-05 — stages 0.9 through 0.11 RC\n\n'
            f'{test_count} Python tests and all nine native contract scenarios pass locally. '
            'Live VK search/play/pause is verified with a muted browser; one own Saved Messages note persisted after reload, with a reused receipt on duplicate operation. '
            'A modern ambiguous contact search returned two candidates without opening a chat. Live Telegram is deferred by the user while my.telegram.org blocks app creation. '
            'Real weather and YouTube lookups and DOCX create/fill/source-preservation checks pass.\n\n'
            'GPT-6 Sol high completed a source demo with two workers, checks and independent review for $0.0484112. '
            'The final frozen EXE also completed a separate two-worker coding demo for $0.033351; both kept the original checkout unchanged. '
            'Frozen runtime/doctor/control/offline command/UI checks pass after installation into a path containing Cyrillic and spaces, with empty private data and a Windows-only PATH. '
            'UTF-8 process manifests fixed the Vosk Unicode path failure. The package contains no key or personal voice. '
            'Installer unit checks cover upgrade, rollback, corruption, extra files, foreign-directory protection and actual temporary uninstall preserving personal settings.\n\n'
            'Limits: this is the same Windows installation with isolated data, not a clean VM or the uncle PC. '
            'Actual logon autostart, uncle hardware/pilot, selected ordinary VK recipients and live Telegram remain external acceptance checks. '
            'The artifact remains a prerelease; no stable 1.0 is claimed.\n')
        f.write('\nPrivacy update requested by the owner: local dictation, no chat context to cloud AI. '
            f'{test_count} tests include private direct/background/error/status paths, freeform dictation, credentials, explicit project selection, private TTS, ASR rejection, redirect/origin restrictions, UTF-8 browser-worker IPC and a real Chromium canary fetch blocked before transport. '
            'The offline privacy-check command uses synthetic accounts and fake transports. A real own VK note through the protected browser/IPC path reached zero cloud model calls and was absent from subsequent model history. '
            'Public Sol/Terra tool rounds and a light-model greeting work with ZDR/data_collection=deny. '
            'Six logical coding tasks are executed in bounded two-worker waves in the Git integration test. '
            'This module is not an OS firewall/sandbox; untrusted code still requires separate isolation.\n')

if __name__=='__main__':main()
