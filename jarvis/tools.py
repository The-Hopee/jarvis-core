from dataclasses import dataclass
from urllib.parse import quote, urlsplit, urlunsplit
import re
import uuid

from jsonschema import Draft202012Validator

from .http import ServiceError
from .ipc import KernelError
from .media import YouTube, youtube_query
from .chat_intents import chat_intent


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
               "ютьюб": "https://www.youtube.com/", "ютюб": "https://www.youtube.com/", "яндекс": "https://ya.ru/", "google": "https://www.google.com/",
               "вконтакте": "https://vk.com/", "вк": "https://vk.com/", "vk": "https://vk.com/"}
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
        self.youtube = YouTube(kernel)
        self.user_request, self.request_id, self.can_send = "", uuid.uuid4().hex, False
        self.can_code = False
        from .config import Settings
        from .telegram_api import TelegramAPI
        from .vk_browser import VKBrowser
        from .openrouter import OpenRouterClient
        settings = getattr(services, 'settings', Settings())
        self.telegram = TelegramAPI(settings)
        self.vk = VKBrowser()
        self.chat_model = OpenRouterClient(settings.api_key, settings.model, max_tokens=1200) if settings.api_key else None
        text = {"type": "string", "minLength": 1, "maxLength": 200}
        city = {"type": "string", "maxLength": 100}
        self.tools = {}
        self.register(Tool("get_system_status", "Текущее состояние компьютера: загрузка CPU, RAM, диски, время работы. Только фактические измерения.", schema(), self.system_status))
        self.register(Tool("open_website", "Открыть сайт в браузере. target: адрес сайта или youtube/ютуб. Не выполняет системные команды.", schema({"target": {"type": "string", "minLength": 1, "maxLength": 4096}}, ["target"]), self.open_website))
        self.register(Tool("search_youtube", "Найти реальные видео на YouTube по названию, исполнителю или описанию. Возвращает названия, ссылки и порядковые номера.", schema({"query": text, "limit": {"type": "integer", "minimum": 1, "maximum": 5}}, ["query"]), self.youtube.search))
        self.register(Tool("open_youtube_video", "Найти и открыть конкретное видео YouTube. Для «открой на ютубе видео Егора Крида» передай query=Егор Крид. По умолчанию выбирается первое видео, index позволяет выбрать другое.", schema({"query": text, "index": {"type": "integer", "minimum": 1, "maximum": 5}}, ["query"]), self.youtube.open_video))
        self.register(Tool("list_applications", "Узнать зарегистрированные приложения и их app_id.", schema(), lambda: kernel.call("list_apps")["result"]))
        self.register(Tool("open_application", "Открыть установленное приложение по app_id, например telegram, notepad, calc. Не отправляет сообщения.", schema({"app_id": text}, ["app_id"]), self.open_application))
        self.register(Tool("get_location", "Определить местоположение: Windows, заданный город или приблизительно IP. Учитывай источник и точность.", schema(), services.location))
        self.register(Tool("get_weather", "Получить актуальную погоду и прогноз на два дня по текущему местоположению или явно названному городу.", schema({"city": city}), services.weather))
        self.register(Tool("find_places", "Найти реальные парки, кафе, рестораны или музеи через OpenStreetMap. При приблизительной геолокации не обещай близость к дому.", schema({"category": {"type": "string", "enum": ["parks", "cafes", "restaurants", "museums"]}, "city": city,
            "radius_m": {"type": "integer", "minimum": 500, "maximum": 10000}, "limit": {"type": "integer", "minimum": 1, "maximum": 5}}), services.places))
        from .coding import projects, start_job, job_status
        self.register(Tool("list_coding_projects", "Показать локально зарегистрированные проекты для кодящих агентов.", schema(), lambda: {"projects": list(projects())}))
        self.register(Tool("start_coding_task", "Запустить кодящую задачу для зарегистрированного проекта: мастер, до двух параллельных субагентов, тесты и ревью в отдельных Git worktree. Возвращает job_id; результат проверяй coding_job_status. Не обещай готовность до завершения.", schema({"project_id": text, "goal": {"type": "string", "minLength": 1, "maxLength": 8000}}, ["project_id", "goal"]), self.start_coding_task))
        self.register(Tool("coding_job_status", "Проверить состояние кодящей задачи, ветку результата, проверки и замечания ревью.", schema({"job_id": {"type": "string", "pattern": "^[a-f0-9]{24}$"}}, ["job_id"]), job_status))
        target = {"platform": {"type": "string", "enum": ["telegram", "vk"]}, "recipient": text}
        self.register(Tool("open_dialog", "Открыть конкретный личный диалог Telegram или VK. Если совпало несколько людей, покажи кандидатов и уточни адресата.", schema(target, ["platform", "recipient"]), self.open_dialog))
        self.register(Tool("read_dialog", "Прочитать последние сообщения выбранного личного диалога и отметить исходящие сообщения владельца.", schema({**target, "limit": {"type": "integer", "minimum": 1, "maximum": 30}}, ["platform", "recipient"]), self.read_dialog))
        self.register(Tool("send_message", "Отправить продиктованный пользователем текст выбранному человеку. Только по прямой просьбе написать/отправить; не перефразируй диктуемый текст.", schema({**target, "text": {"type": "string", "minLength": 1, "maxLength": 4000}}, ["platform", "recipient", "text"]), self.send_message))
        self.register(Tool("draft_reply", "Подготовить текст ответа по контексту и примерам исходящих сообщений владельца, без отправки.", schema({**target, "instruction": {"type": "string", "maxLength": 1500}}, ["platform", "recipient"]), self.draft_reply))
        self.register(Tool("reply_in_my_style", "По прямой просьбе пользователя прочитать выбранный диалог, составить ответ в его стиле и отправить. Не использовать для просьбы только показать черновик.", schema({**target, "instruction": {"type": "string", "maxLength": 1500}}, ["platform", "recipient"]), self.reply_in_my_style))

    def begin_turn(self, text):
        self.user_request, self.request_id = text, uuid.uuid4().hex
        self.can_code = bool(re.search(r"(?:код|проект|репозитор|программ|модул|функци|тест|сервис)", text, re.I)
                             and re.search(r"напиш|исправ|реализ|добав|сделай|разработ|почини", text, re.I))
        self.can_send = bool(re.search(r"\b(?:напиш\w*|отправ\w*|ответь|скажи|передай|send|reply)\b", text, re.I))
        if re.search(r"\bне\s+(?:отправ\w*|пиш\w*|отвеч\w*)|черновик|без\s+отправки|сначала\s+покажи", text, re.I):
            self.can_send = False

    def start_coding_task(self, project_id, goal):
        from .coding import start_job
        if not self.can_code:
            raise ServiceError('Кодящая задача не запрошена в текущем обращении пользователя')
        return start_job(project_id, goal)

    def close(self):
        self.vk.close()

    def _backend(self, platform):
        return self.telegram if platform == 'telegram' else self.vk

    def open_dialog(self, platform, recipient):
        if platform == 'telegram':
            return self.telegram.open(recipient, self.kernel)
        return self.vk.open(recipient)

    def read_dialog(self, platform, recipient, limit=30):
        return self._backend(platform).read(recipient, limit=limit)

    def send_message(self, platform, recipient, text):
        if not self.can_send:
            raise ServiceError('В текущем запросе нет разрешения на отправку. Для черновика используй draft_reply.')
        return self._backend(platform).send(recipient, text, operation_id=self.request_id)

    def draft_reply(self, platform, recipient, instruction='Ответь по контексту в моём стиле'):
        from .messaging import draft_reply
        dialogue = self.read_dialog(platform, recipient, limit=30)
        if not dialogue.get('recipient'):
            return dialogue
        draft = draft_reply(self.chat_model, dialogue, instruction)
        return {**draft, 'recipient': dialogue['recipient'], 'status': 'draft', 'sent': False}

    def reply_in_my_style(self, platform, recipient, instruction='Ответь по контексту в моём стиле'):
        if not self.can_send:
            raise ServiceError('Отправка не запрошена: можно подготовить draft_reply без отправки.')
        draft = self.draft_reply(platform, recipient, instruction)
        if not draft.get('recipient'):
            return draft
        username = draft['recipient'].get('username')
        target = ('@' + username if username else draft['recipient']['id']) if platform == 'telegram' else draft['recipient']['name']
        result = self.send_message(platform, target, draft['text'])
        return {**result, 'style_examples_used': draft['style_examples_used']}

    def register(self, tool):
        Draft202012Validator.check_schema(tool.parameters)
        if tool.name in self.tools:
            raise ValueError("Повторное имя инструмента")
        self.tools[tool.name] = tool

    def definitions(self):
        return [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
                for t in self.tools.values() if (self.can_send or t.name not in {'send_message', 'reply_in_my_style'})
                and (self.can_code or t.name != 'start_coding_task')]

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
        query = youtube_query("открой " + target)
        if query:
            return self.youtube.open_video(query)
        intent = chat_intent("открой " + target)
        if intent and intent[0] == "open_dialog":
            return self.open_dialog(**intent[1])
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
