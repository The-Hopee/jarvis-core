"""Pre-rendered public acknowledgements, playable locally during private turns."""
import hashlib
from pathlib import Path
from .progress import cache_directory

PHRASES=('В VK или Telegram, сэр?','Кому отправить сообщение, сэр?',
         'Какой текст отправить, сэр?','Отправка отменена, сэр.',
         'Сообщение отправлено, сэр.','Сначала откройте нужный диалог, сэр.',
         'Уточните мессенджер: VK или Telegram, сэр?',
         'Кому и в каком мессенджере написать, сэр?')


def cached_reply(settings,text):
    if text not in PHRASES:return None
    key=hashlib.sha256(('qwen-tts-0.6b-bf16-v1:'+text).encode()).hexdigest()[:24]
    reference=getattr(settings,'private_voice_reference','')
    if reference and Path(reference).is_file():
        fingerprint=hashlib.sha256(Path(reference).read_bytes()+settings.private_voice_reference_text.encode()).hexdigest()
        key=hashlib.sha256((key+fingerprint).encode()).hexdigest()[:24]
    return cache_directory(settings)/'private-replies'/(key+'.wav')
