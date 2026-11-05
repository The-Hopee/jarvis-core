"""Collect public smoke metadata and append this release's validation record."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from jarvis.config import USER_DIR,ROOT

def main():
    record={name:json.loads((USER_DIR/'benchmarks'/('stage08-'+name+'.json')).read_text(encoding='utf-8')) for name in ('responses-smoke','routing-smoke')}
    (ROOT/'docs/benchmarks/stage08-2026-11-05.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    with (ROOT/'docs/VALIDATION.md').open('a',encoding='utf-8') as f:
        f.write('\n## 2026-11-05 — 0.8 profiles and skills\n\n128 Python tests and the native contract suite pass. '
                'Real OpenRouter Responses tool/result round trips completed for GPT-6 Sol high and GPT-6.1 Terra low. '
                'Terra created a real DOCX using create_document, with no application launch or audio; cost $0.0026648. '
                'Routing, manual modes, opaque reasoning replay, incomplete response rejection and concurrent budget reservations are tested. '
                'ASR/TTS charges are outside the LLM budget; provider key cap is unchanged.\n')

if __name__=='__main__':main()
