"""Data minimization before serialization; credential filter and HTTP boundary.

This is an application policy, not an OS sandbox or a whole-PC network monitor.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime,timezone
import json
import re
import sqlite3
import threading
import urllib.request
from urllib.parse import urlsplit

from .config import USER_DIR
from .http import ServiceError

PRIVATE_TOOLS={'open_dialog','read_dialog','send_message','draft_reply','reply_in_my_style'}
HOSTS={'openrouter.ai','api.elevenlabs.io','ipapi.co','geocoding-api.open-meteo.com',
       'api.open-meteo.com','maps.mail.ru','overpass.private.coffee','www.youtube.com'}
_secrets=set();_lock=threading.RLock();_opener_installed=False
_private=ContextVar('jarvis_private_data',default=False)
_settings=ContextVar('jarvis_privacy_settings',default=None)
KEY_PATTERN=re.compile(r'(?i)(?:sk-(?:or-v1-)?[a-z0-9_-]{16,}|(?:api[_ -]?key|api[_ -]?hash|access[_ -]?token|authorization|password|пароль)\s*[:=]\s*["\']?[^\s"\',;}]{8,})')

class PrivacyBlocked(ServiceError):pass

class PrivateText(str):
    """Local display/speech only. Never flatten this label into a cloud payload."""
    pass

def register_secrets(settings):
    with _lock:
        for name in ('api_key','elevenlabs_api_key','telegram_api_hash'):
            value=getattr(settings,name,'')
            if len(value)>=12:_secrets.add(value)

def audit(event,category,destination=''):
    # Fixed metadata only: no message, URL query, recipient, credential or body hash.
    path=USER_DIR/'privacy-audit.sqlite';path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path,timeout=5)
    try:
        with db:
            db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, at TEXT, event TEXT, category TEXT, destination TEXT)')
            db.execute('INSERT INTO events(at,event,category,destination) VALUES (?,?,?,?)',
                       (datetime.now(timezone.utc).isoformat(timespec='seconds'),event,category,destination))
            db.execute('DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 2000)')
    finally:db.close()

def report():
    path=USER_DIR/'privacy-audit.sqlite'
    if not path.exists():return {'events':[]}
    db=sqlite3.connect(path,timeout=5)
    try:return {'events':[dict(zip(('event','category','destination','count'),row)) for row in db.execute('SELECT event,category,destination,COUNT(*) FROM events GROUP BY event,category,destination')]}
    finally:db.close()

@contextmanager
def context(settings=None,*,private=False):
    first=_settings.set(settings);second=_private.set(private)
    try:yield
    finally:_private.reset(second);_settings.reset(first)

def private_request(text):
    return bool(re.search(r'телеграм|telegram|\bтг\b|вконтакт|\bвк\b|\bvk\b|диалог|переписк|сообщени|мо[её]м стиле',text,re.I))

def chat_action(text):
    if re.search(r'телеграм|telegram|\bтг\b|вконтакт|\bвк\b|\bvk\b|диалог|переписк|мо[её]м стиле',text,re.I):return True
    first=re.search(r'\b(?:напиш\w*|напис\w*|отправ\w*|скажи|передай|ответь)\b',text,re.I)
    if first:
        # Only the direct object of the first verb can classify a technical task;
        # keywords inside dictated message text must never grant a cloud route.
        return not bool(re.match(r'\s+(?:код\b|модул|программ|функци|тест|документ|отч[её]т|стать|резюме|договор|сказк)',text[first.end():],re.I))
    return bool(re.search(r'сообщени',text,re.I))

def clean_text(text):
    if isinstance(text,PrivateText):raise PrivacyBlocked('Приватный текст запрещено передавать облачному ИИ')
    with _lock:
        for secret in sorted(_secrets,key=len,reverse=True):text=text.replace(secret,'[SECRET REMOVED]')
    return KEY_PATTERN.sub('[SECRET REMOVED]',text)

def clean(value):
    if isinstance(value,str):return clean_text(value)
    if isinstance(value,dict):
        return {k:('[SECRET REMOVED]' if re.fullmatch(r'(?i)(?:api_key|api_hash|access_token|auth_key|password|session|cookie|authorization)',k) else clean(v)) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [clean(v) for v in value]
    return value

def cloud_context(value):
    # The real local context still resolves pronouns and recipient choices.
    return clean({k:v for k,v in value.items() if k not in {'dialog','recipient_name'}})

def cloud_tool(name,output):
    if not output.get('ok'):
        return {'ok':False,'error':'Локальная ошибка инструмента; подробности не передаются модели.'}
    if name in PRIVATE_TOOLS:
        audit('blocked','chat_tool_result','cloud_model')
        return {'ok':bool(output.get('ok')),'result':{'private_content_withheld':True,'status':output.get('result',{}).get('status','local_only')}}
    return clean(output)

def model_body(body,settings=None):
    settings=settings or _settings.get()
    if _private.get() or getattr(settings,'privacy_mode','strict')=='offline_ai':
        audit('blocked','private_or_offline','cloud_model')
        raise PrivacyBlocked('Защита приватности: этот запрос не отправлен облачной модели')
    original=json.dumps(body,ensure_ascii=False,default=str)
    body=clean(body)
    if json.dumps(body,ensure_ascii=False,default=str)!=original:audit('redacted','credentials','cloud_model')
    provider=dict(body.get('provider') or {})
    provider.update(data_collection='deny',zdr=True)
    body['provider']=provider
    audit('allowed','public_model','openrouter.ai')
    return body

def require_chat_cloud():
    audit('blocked','chat_context','cloud_model')
    raise PrivacyBlocked('Переписка остаётся на ПК. Облачный ответ «в моём стиле» отключён защитой приватности.')

def require_audio(settings,*,transcription=False,text=None):
    if getattr(settings,'privacy_mode','strict')=='offline_ai' or isinstance(text,PrivateText) or _private.get():
        audit('blocked','private_audio','cloud_audio');raise PrivacyBlocked('Приватная речь озвучивается и распознаётся только локально')
    if transcription and not getattr(settings,'allow_cloud_asr',False):
        audit('blocked','voice_recording','cloud_asr');raise PrivacyBlocked('Облачное распознавание отключено: голосовая запись остаётся на ПК')
    if text is not None and clean_text(text)!=text:
        audit('blocked','credential_speech','cloud_tts');raise PrivacyBlocked('Секретные данные не передаются облачному голосу')

class NoCrossOriginRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,request,fp,code,message,headers,newurl):
        before,after=urlsplit(request.full_url),urlsplit(newurl)
        if (before.scheme,before.hostname,before.port)!=(after.scheme,after.hostname,after.port):
            audit('blocked','redirect','different_origin');raise PrivacyBlocked('Перенаправление на другой сервер заблокировано')
        return super().redirect_request(request,fp,code,message,headers,newurl)

def check_url(url):
    global _opener_installed
    parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.hostname not in HOSTS or parsed.port not in (None,443) or parsed.username or parsed.password:
        audit('blocked','destination','unapproved_host');raise PrivacyBlocked('Сетевой адрес не входит в список сервисов Jarvis')
    with _lock:
        if not _opener_installed:
            urllib.request.install_opener(urllib.request.build_opener(NoCrossOriginRedirect()))
            _opener_installed=True
    audit('allowed','http',parsed.hostname)
