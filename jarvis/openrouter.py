from .http import ServiceError, request_json


class OpenRouterClient:
    def __init__(self, api_key: str, model: str, http=request_json):
        self._api_key, self.model, self.http = api_key, model, http

    def complete(self, messages: list, tools: list, *, allow_tools=True):
        if not self._api_key:
            raise ServiceError("Добавьте OPENROUTER_API_KEY в .env")
        body = {"model": self.model, "messages": messages, "tools": tools,
                "tool_choice": "auto" if allow_tools else "none", "parallel_tool_calls": False,
                "max_tokens": 600, "provider": {"require_parameters": True}}
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
