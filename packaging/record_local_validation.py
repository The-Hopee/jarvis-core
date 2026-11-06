"""Export local-model acceptance metadata, excluding voices, contacts and text."""
import json
from pathlib import Path
import re
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from jarvis.config import ROOT,USER_DIR,Settings
from jarvis.local_voice_cache import PHRASES,cached_reply


def main():
    raw=(ROOT/'build/tests-local-ai-publish.log').read_bytes()
    text=raw.decode('utf-16' if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8',errors='replace')
    matches=re.findall(r'Ran\s+(\d+)\s+tests',text)
    if not matches or not re.search(r'\bOK\s*$',text):raise RuntimeError('Final successful test report missing')
    records={}
    for label,name in (('llm','local-ai-real-smoke'),('voice','local-voice-real-smoke-target-a'),
                       ('lifecycle','local-lifecycle-real-smoke'),('live_vk','stage11-private-vk-smoke')):
        records[label]=json.loads((USER_DIR/'benchmarks'/(name+'.json')).read_text(encoding='utf-8'))
    for label in ('llm','voice','lifecycle'):
        for stage in ('before_exit','after_exit','before_idle','after_idle'):
            if stage in records[label]:records[label][stage]={role:{'running':value['running']} for role,value in records[label][stage].items()}
    manifest=json.loads((USER_DIR/'local-model-install.json').read_text(encoding='utf-8'))
    settings=Settings.load()
    records['installation']={'revisions':manifest['revisions'],'llama':manifest['llama_version'],
                            'verified_files':len(manifest['files']),'weights_and_archives_bytes':sum(x['size'] for x in manifest['files'])}
    records['acceptance']={'python_tests':int(matches[-1]),'voice_accepted_by_owner':True,
                           'cached_fixed_replies':sum(cached_reply(settings,t).is_file() for t in PHRASES)}
    destination=ROOT/'docs/benchmarks/local-ai-2026-11-06.json'
    destination.write_text(json.dumps(records,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'saved':destination.name,'tests':int(matches[-1])}))


if __name__=='__main__':main()
