"""One persistent native child; correlated UTF-8 JSON lines, bounded waits, no replay."""
from collections import deque
import json
from pathlib import Path
import queue
import subprocess
import threading
import uuid


class KernelError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class JsonProcessClient:
    def __init__(self, command: list[str], timeout: float = 15, cwd=None):
        self.timeout = timeout
        self._lock = threading.Lock()
        self._queue = queue.Queue(maxsize=4)
        self._stderr = deque(maxlen=10)
        self._closed = False
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1,
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), cwd=cwd)
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._errors = threading.Thread(target=self._read_errors, daemon=True)
        self._reader.start()
        self._errors.start()

    def _read(self):
        try:
            while line := self.process.stdout.readline(8 * 1024 * 1024 + 1):
                if len(line.encode("utf-8")) > 8 * 1024 * 1024:
                    raise ValueError("Ответ ядра превысил лимит")
                self._queue.put_nowait(line)
        except (OSError, ValueError, queue.Full) as exc:
            try:
                self._queue.put_nowait(exc)
            except queue.Full:
                pass
        finally:
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                pass

    def _read_errors(self):
        try:
            for line in self.process.stderr:
                self._stderr.append(line.rstrip()[:1000])
        except (OSError, ValueError):
            pass

    def call(self, method: str, params: dict | None = None) -> dict:
        with self._lock:
            if self._closed:
                raise KernelError("ipc_closed", "Соединение с ядром закрыто")
            request_id = uuid.uuid4().hex
            line = json.dumps({"protocol_version": 1, "id": request_id, "method": method,
                               "params": params if params is not None else {}}, ensure_ascii=False)
            if len(line.encode("utf-8")) > 1024 * 1024:
                raise KernelError("request_too_large", "Запрос к ядру слишком большой")
            try:
                self.process.stdin.write(line + "\n")
                self.process.stdin.flush()
                raw = self._queue.get(timeout=self.timeout)
                if raw is None or isinstance(raw, Exception):
                    raise ValueError("Ядро закрыло канал связи")
                response = json.loads(raw)
                if not isinstance(response, dict) or response.get("id") != request_id or response.get("protocol_version") != 1:
                    raise ValueError("Ответ ядра не соответствует запросу")
                if not isinstance(response.get("ok"), bool):
                    raise ValueError("Некорректный статус ядра")
            except (OSError, ValueError, queue.Empty) as exc:
                self.close()
                raise KernelError("ipc_failed", "Ядро не ответило корректно. Команда не повторялась; перезапустите Джарвиса.") from exc
            if not response["ok"]:
                error = response.get("error") or {}
                raise KernelError(error.get("code", "native_error"), error.get("message", "Ошибка ядра"))
            return response

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self.process.stdin.close()
        except OSError:
            pass
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=3)
        self._reader.join(timeout=1)
        self._errors.join(timeout=1)
        self.process.stdout.close()
        self.process.stderr.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class KernelClient(JsonProcessClient):
    def __init__(self, executable: Path, config: Path | None = None, timeout: float = 15):
        if not executable.is_file():
            raise KernelError("kernel_missing", f"Не найдено C++-ядро: {executable}. Запустите setup.ps1.")
        command = [str(executable), "--stdio", "--enable-actions"]
        if config:
            command += ["--config", str(config)]
        super().__init__(command, timeout=timeout)
