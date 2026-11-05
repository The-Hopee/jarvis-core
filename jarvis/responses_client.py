"""OpenRouter Responses adapter with verbatim reasoning/function-call replay."""
from .http import request_json,ServiceError
from .telemetry import measure
from contextlib import nullcontext


class ResponsesClient:
    def __init__(self,api_key,model,*,effort='low',max_tokens=4000,http=request_json,budget=None,pricing=None):
        self._api_key,self.model,self.effort=api_key,model,effort
        self.max_tokens,self.http=max_tokens,http
        self.budget,self.pricing=budget,pricing
        self.last_usage={}

    @staticmethod
    def input_items(messages):
        result=[]
        for message in messages:
            role=message.get('role')
            if role=='tool':
                result.append({'type':'function_call_output','call_id':message['tool_call_id'],'output':message['content']})
            elif role=='assistant' and message.get('_response_items'):
                # Encrypted reasoning/signatures are opaque protocol state.
                result.extend(message['_response_items'])
            else:
                if message.get('content') is not None:result.append({'role':role,'content':message['content']})
                for call in message.get('tool_calls') or []:
                    function=call['function']
                    result.append({'type':'function_call','call_id':call['id'],'name':function['name'],'arguments':function['arguments']})
        return result

    def complete(self,messages,tools,*,allow_tools=True):
        if not self._api_key:raise ServiceError('Добавьте OPENROUTER_API_KEY в локальные настройки')
        body={'model':self.model,'input':self.input_items(messages),'max_output_tokens':self.max_tokens,'store':False}
        if self.effort:body['reasoning']={'effort':self.effort}
        if self.model.startswith('openai/'):
            body['include']=['reasoning.encrypted_content']
        if tools:
            body['tools']=[{'type':'function',**tool['function'],'strict':False} for tool in tools]
            body['tool_choice']='auto' if allow_tools else 'none'
        with self.budget.call(body,self.model,self.max_tokens) if self.budget else nullcontext({}) as usage:
            with measure('model',self.model):
                response=self.http('https://openrouter.ai/api/v1/responses',data=body,
                headers={'Authorization':'Bearer '+self._api_key,'X-Title':'Jarvis Home'},timeout=45,max_bytes=2*1024*1024)
            if isinstance(response,dict) and isinstance(response.get('usage'),dict):usage.update(response['usage'])
        if not isinstance(response,dict) or response.get('error') or response.get('status')!='completed':
            raise ServiceError('Модель не завершила ответ Responses; действия не выполнялись')
        output=response.get('output')
        if not isinstance(output,list):raise ServiceError('Некорректный результат Responses')
        text=[];calls=[]
        for item in output:
            if item.get('type')=='function_call':
                if not all(isinstance(item.get(k),str) for k in ('call_id','name','arguments')):
                    raise ServiceError('Некорректный вызов инструмента Responses')
                calls.append({'id':item['call_id'],'type':'function','function':{'name':item['name'],'arguments':item['arguments']}})
            elif item.get('type')=='message':
                for part in item.get('content',[]):
                    if part.get('type')=='output_text':text.append(part.get('text',''))
                    elif part.get('type')=='refusal':text.append(part.get('refusal','Модель отказалась выполнять запрос.'))
        if not text and not calls:raise ServiceError('Модель вернула пустой ответ Responses')
        if calls and not allow_tools:raise ServiceError('Инструменты запрещены для этого шага')
        self.last_usage=response.get('usage') or {}
        result={'role':'assistant','content':''.join(text),'_response_items':output}
        if calls:result['tool_calls']=calls
        return result
