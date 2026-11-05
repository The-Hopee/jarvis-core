from .http import ServiceError, request_json
from .telemetry import measure


class OpenRouterClient:
    def __init__(self, api_key: str, model: str, http=request_json, max_tokens=600):
        self._api_key, self.model, self.http = api_key, model, http
        self.max_tokens = max_tokens

    def stream_complete(self,messages,tools,*,allow_tools=False,on_text=None):
        from .text_stream import events,completion
        if allow_tools or tools:
            raise ServiceError('Голосовой поток разрешён только для ответа без инструментов')
        body={'model':self.model,'messages':messages,'max_tokens':self.max_tokens,'stream':True}
        with measure('model',self.model):
            return completion(events(body,{'Authorization':'Bearer '+self._api_key,'X-Title':'Jarvis Home'}),on_text)

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
        with measure('model', self.model):
            response = self.http("https://openrouter.ai/api/v1/chat/completions", data=body,
                                 headers={"Authorization": "Bearer " + self._api_key, "X-Title": "Jarvis Home"},
                                 timeout=45)
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
