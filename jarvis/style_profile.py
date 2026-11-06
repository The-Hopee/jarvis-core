"""Explicitly learned, local-only outgoing writing examples per selected contact."""
import hashlib
import json
from pathlib import Path
import statistics
import threading

from .config import USER_DIR
from .privacy import clean_text

_LOCKS={};_LOCKS_GUARD=threading.Lock()


class StyleStore:
    def __init__(self,path=None):
        self.path=Path(path or USER_DIR/'private/style.json')
        with _LOCKS_GUARD:self.lock=_LOCKS.setdefault(str(self.path.resolve()),threading.RLock())
    def _load(self):
        if not self.path.exists():return {'version':1,'rules':[],'contacts':{}}
        if self.path.stat().st_size>2*1024*1024:raise ValueError('Style profile exceeds limit')
        return json.loads(self.path.read_text(encoding='utf-8'))
    def _save(self,data):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temporary=self.path.with_suffix('.tmp');temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        temporary.replace(self.path)
    @staticmethod
    def key(platform,recipient):return hashlib.sha256(f'{platform}:{recipient}'.encode()).hexdigest()
    @staticmethod
    def sample(text):
        if not isinstance(text,str) or not 0<len(text)<=2000:return None
        if clean_text(str(text))!=str(text):return None
        return text.strip()
    def learn(self,platform,dialogue):
        samples=[self.sample(m.get('text')) for m in dialogue.get('messages',[]) if m.get('outgoing')]
        samples=list(dict.fromkeys(s for s in samples if s))[-60:]
        with self.lock:
            data=self._load();key=self.key(platform,dialogue['recipient']['id'])
            data['contacts'][key]={'examples':samples,'enabled':True}
            self._save(data)
        return len(samples)
    def record(self,platform,recipient,text):
        text=self.sample(text)
        if not text:return
        with self.lock:
            data=self._load();profile=data['contacts'].get(self.key(platform,recipient))
            if not profile or not profile.get('enabled'):return
            profile['examples']=list(dict.fromkeys([*profile['examples'],text]))[-60:];self._save(data)
    def context(self,platform,recipient):
        with self.lock:
            data=self._load();examples=data['contacts'].get(self.key(platform,recipient),{}).get('examples',[])[-12:]
            return {'rules':data.get('rules',[])[:20],'examples':examples,
                    'median_characters':round(statistics.median(map(len,examples))) if examples else None}
