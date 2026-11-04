import json
import urllib.error
import urllib.request


class ServiceError(RuntimeError):
    pass


def request_json(url: str, *, data: dict | bytes | None = None, headers: dict | None = None,
                 timeout: float = 15, max_bytes: int = 2 * 1024 * 1024):
    request_headers = {"User-Agent": "JarvisHome/0.2 (personal desktop assistant)", "Accept": "application/json"}
    if isinstance(data, dict):
        data = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request_headers.update(headers or {})
    request = urllib.request.Request(url, data=data, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise ServiceError("Ответ внешнего сервиса слишком большой")
        return json.loads(raw)
    except urllib.error.HTTPError as exc:
        # Never include request headers, keys or an untrusted response body in an error.
        hints = {401: "проверьте API-ключ", 402: "проверьте баланс", 403: "доступ запрещён", 429: "лимит запросов"}
        raise ServiceError(f"HTTP {exc.code}: {hints.get(exc.code, 'ошибка внешнего сервиса')}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise ServiceError("Внешний сервис недоступен или вернул некорректные данные") from exc
