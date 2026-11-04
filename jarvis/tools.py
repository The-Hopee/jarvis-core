from dataclasses import dataclass
from urllib.parse import quote, urlsplit, urlunsplit

from jsonschema import Draft202012Validator

from .http import ServiceError
from .ipc import KernelError


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    handler: object


def schema(properties=None, required=None):
    return {"type": "object", "properties": properties or {}, "required": required or [], "additionalProperties": False}


def normalize_url(target: str) -> str:
    aliases = {"ютуб": "https://www.youtube.com/", "youtube": "https://www.youtube.com/",
               "ютьюб": "https://www.youtube.com/", "ютюб": "https://www.youtube.com/", "яндекс": "https://ya.ru/", "google": "https://www.google.com/"}
    target = aliases.get(target.strip().casefold(), target.strip())
    if any(ord(c) < 32 or c in '\\"' for c in target):
        raise ValueError("Адрес содержит недопустимые символы")
    if "://" not in target:
        target = "https://" + target
    parts = urlsplit(target)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("Нужен адрес сайта HTTP(S) без логина и пароля")
    host = parts.hostname.encode("idna").decode("ascii")
    if " " in host or "." not in host and host != "localhost" or any(c in host for c in '/?#%'):
        raise ValueError("Не удалось распознать адрес сайта")
    if ":" in host:  # Preserve IPv6 brackets.
        host = "[" + host + "]"
    if parts.port:
        host += ":" + str(parts.port)
    url = urlunsplit((parts.scheme, host, quote(parts.path, safe="/%:@!$&'()*+,;=-._~"),
                      quote(parts.query, safe="%=&?/:@!$'()*+,;~-._"), quote(parts.fragment, safe="%~-._")))
    if len(url.encode("utf-8")) > 4096:
        raise ValueError("Слишком длинный адрес")
    return url


class ToolRegistry:
    def __init__(self, kernel, services):
        self.kernel, self.services = kernel, services
        text = {"type": "string", "minLength": 1, "maxLength": 200}
        city = {"type": "string", "maxLength": 100}
        self.tools = {}
        self.register(Tool("get_system_status", "Текущее состояние компьютера: загрузка CPU, RAM, диски, время работы. Только фактические измерения.", schema(), self.system_status))
        self.register(Tool("open_website", "Открыть сайт в браузере. target: адрес сайта или youtube/ютуб. Не выполняет системные команды.", schema({"target": {"type": "string", "minLength": 1, "maxLength": 4096}}, ["target"]), self.open_website))
        self.register(Tool("list_applications", "Узнать зарегистрированные приложения и их app_id.", schema(), lambda: kernel.call("list_apps")["result"]))
        self.register(Tool("open_application", "Открыть установленное приложение по app_id, например telegram, notepad, calc. Не отправляет сообщения.", schema({"app_id": text}, ["app_id"]), self.open_application))
        self.register(Tool("get_location", "Определить местоположение: Windows, заданный город или приблизительно IP. Учитывай источник и точность.", schema(), services.location))
        self.register(Tool("get_weather", "Получить актуальную погоду и прогноз на два дня по текущему местоположению или явно названному городу.", schema({"city": city}), services.weather))
        self.register(Tool("find_places", "Найти реальные парки, кафе, рестораны или музеи через OpenStreetMap. При приблизительной геолокации не обещай близость к дому.", schema({"category": {"type": "string", "enum": ["parks", "cafes", "restaurants", "museums"]}, "city": city,
            "radius_m": {"type": "integer", "minimum": 500, "maximum": 10000}, "limit": {"type": "integer", "minimum": 1, "maximum": 5}}), services.places))

    def register(self, tool):
        Draft202012Validator.check_schema(tool.parameters)
        if tool.name in self.tools:
            raise ValueError("Повторное имя инструмента")
        self.tools[tool.name] = tool

    def definitions(self):
        return [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
                for t in self.tools.values()]

    def execute(self, name, arguments):
        tool = self.tools.get(name)
        if not tool:
            return {"ok": False, "error": {"code": "unknown_tool", "message": "Неизвестный инструмент"}}
        try:
            errors = list(Draft202012Validator(tool.parameters).iter_errors(arguments))
            if errors:
                raise ValueError("Параметры не соответствуют схеме инструмента")
            return {"ok": True, "result": tool.handler(**arguments)}
        except (KernelError, ServiceError, ValueError, TypeError, KeyError) as exc:
            return {"ok": False, "error": {"code": getattr(exc, "code", "tool_failed"), "message": str(exc)[:500]}}

    def open_website(self, target):
        return self.kernel.call("open_url", {"url": normalize_url(target)})["result"]

    def open_application(self, app_id):
        aliases = {"телеграм": "telegram", "телеграмм": "telegram", "телеграмма": "telegram", "телеграмму": "telegram", "калькулятор": "calc", "блокнот": "notepad"}
        app_id = aliases.get(app_id.casefold(), app_id.casefold())
        return self.kernel.call("launch_app", {"app_id": app_id})["result"]

    def system_status(self):
        response = self.kernel.call("system_snapshot", {"checks": ["cpu", "memory", "disk", "system"], "top_processes": 3})
        result = response["result"]
        return {"measured_at": response["timestamp_utc"], "partial": result.get("partial"),
                "metrics": result["metrics"], "diagnostics": result.get("diagnostics", []),
                "note": "Диагностика по порогам; это не доказательство причины неполадок."}
