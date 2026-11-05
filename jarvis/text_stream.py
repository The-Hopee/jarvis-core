"""Bounded SSE text transport. Tool arguments are never executed from partial data."""
import json
import urllib.request
import urllib.error
from .http import ServiceError
from .telemetry import mark


def events(body,headers,*,opener=urllib.request.urlopen):
    request=urllib.request.Request('https://openrouter.ai/api/v1/chat/completions',
        data=json.dumps(body,ensure_ascii=False).encode('utf-8'),headers={**headers,'Content-Type':'application/json','Accept':'text/event-stream'})
    total=0
    try:
        with opener(request,timeout=45) as response:
            while True:
                line=response.readline(256*1024+1)
                if not line:
                    raise ServiceError('Поток модели оборван до завершения')
                total+=len(line)
                if total>4*1024*1024 or len(line)>256*1024:
                    raise ServiceError('Поток модели превысил лимит')
                if not line.startswith(b'data:'):
                    continue
                value=line[5:].strip()
                if value==b'[DONE]':return
                try:payload=json.loads(value)
                except ValueError as exc:raise ServiceError('Некорректное событие модели') from exc
                if not isinstance(payload,dict) or payload.get('error'):
                    raise ServiceError('Модель вернула ошибку в потоке')
                yield payload
    except urllib.error.HTTPError as exc:
        raise ServiceError(f'HTTP {exc.code}: поток модели недоступен') from exc
    except (urllib.error.URLError,TimeoutError,OSError) as exc:
        raise ServiceError('Соединение с потоком модели прервано') from exc


def completion(chunks,on_text=None):
    content=[];calls={};finished=False;first=True
    for chunk in chunks:
        choices=chunk.get('choices') or []
        if not choices:continue
        choice=choices[0]
        if choice.get('finish_reason') in {'stop','tool_calls'}:finished=True
        elif choice.get('finish_reason'):
            raise ServiceError('Модель не завершила ответ в пределах лимита')
        delta=choice.get('delta') or {}
        text=delta.get('content')
        if text:
            if not isinstance(text,str):raise ServiceError('Некорректный текст модели')
            if first:mark('model_first_token');first=False
            content.append(text)
            if sum(map(len,content))>24000:raise ServiceError('Слишком длинный ответ модели')
            if on_text:on_text(text)
        for call in delta.get('tool_calls') or []:
            index=call.get('index',0)
            if not isinstance(index,int) or not 0<=index<8:raise ServiceError('Слишком много вызовов')
            item=calls.setdefault(index,{'id':'','type':'function','function':{'name':'','arguments':''}})
            if call.get('id'):item['id']+=call['id']
            for key in ('name','arguments'):
                if call.get('function',{}).get(key):item['function'][key]+=call['function'][key]
            if len(item['function']['arguments'])>16000:raise ServiceError('Аргументы превысили лимит')
    if not finished:raise ServiceError('Поток модели завершён без результата')
    result={'role':'assistant','content':''.join(content)}
    if calls:
        if on_text:raise ServiceError('Неожиданный инструмент в голосовом ответе')
        result['tool_calls']=[calls[i] for i in sorted(calls)]
    if not result['content'] and not calls:raise ServiceError('Пустой ответ модели')
    return result
