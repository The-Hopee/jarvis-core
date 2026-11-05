from .http import ServiceError, request_json
from .telemetry import measure
from contextlib import nullcontext


class OpenRouterClient:
    def __init__(self, api_key: str, model: str, http=request_json, max_tokens=600, budget=None, effort='',privacy_settings=None):
        self._api_key, self.model, self.http = api_key, model, http
        self.max_tokens = max_tokens
        self.budget,self.effort=budget,effort
        self.last_usage={}
        self.privacy_settings=privacy_settings

    def stream_complete(self,messages,tools,*,allow_tools=False,on_text=None):
        from .text_stream import events,completion
        if allow_tools or tools:
            raise ServiceError('Голосовой поток разрешён только для ответа без инструментов')
        body={'model':self.model,'messages':messages,'max_tokens':self.max_tokens,'stream':True,'stream_options':{'include_usage':True}}
        from .privacy import model_body
        body=model_body(body,self.privacy_settings)
        with self.budget.call(body,self.model,self.max_tokens) if self.budget else nullcontext({}) as usage:
            def chunks():
                for chunk in events(body,{'Authorization':'Bearer '+self._api_key,'X-Title':'Jarvis Home'}):
                    if isinstance(chunk.get('usage'),dict):usage.update(chunk['usage'])
                    yield chunk
            with measure('model',self.model):
                result=completion(chunks(),on_text)
            self.last_usage=usage.copy()
            return result

    def complete(self, messages: list, tools: list, *, allow_tools=True):
        if not self._api_key:
            raise ServiceError("Добавьте OPENROUTER_API_KEY в .env")
        # Some providers (including the current GPT-4.1-mini route) do not
        # advertise parallel_tool_calls. With require_parameters=True, sending
        # even false excludes every endpoint and returns HTTP 404. Execution is
        # serialized and bounded by Assistant, so omit this optional parameter.
        body = {"model": self.model, "messages": messages, "tools": tools,
                "tool_choice": "auto" if allow_tools else "none",
                "max_tokens": self.max_tokens, "provider": {"require_parameters": True}}
        if not tools:
            for key in ("tools", "tool_choice", "parallel_tool_calls"):
                body.pop(key, None)
        if self.effort:body['reasoning']={'effort':self.effort}
        from .privacy import model_body
        body=model_body(body,self.privacy_settings)
        with self.budget.call(body,self.model,self.max_tokens) if self.budget else nullcontext({}) as usage:
            with measure('model', self.model):
                response = self.http("https://openrouter.ai/api/v1/chat/completions", data=body,
                                 headers={"Authorization": "Bearer " + self._api_key, "X-Title": "Jarvis Home"},
                                 timeout=45)
            if isinstance(response,dict) and isinstance(response.get('usage'),dict):usage.update(response['usage'])
            self.last_usage=usage.copy()
        if not isinstance(response, dict) or response.get("error"):
            raise ServiceError("OpenRouter вернул ошибку. Проверьте модель, баланс и поддержку tools.")
        try:
            message = response["choices"][0]["message"]
            if not isinstance(message, dict):
                raise TypeError()
            if not (message.get("content") or message.get("tool_calls")):
                raise ValueError()
            return message
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ServiceError("OpenRouter не вернул текст или вызов инструмента") from exc
