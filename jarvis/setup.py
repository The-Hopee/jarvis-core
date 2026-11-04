import getpass
import json
import os
from pathlib import Path
import subprocess

from .config import USER_DIR


def discover_telegram(settings):
    candidates = []
    if settings.telegram_path:
        candidates.append(Path(settings.telegram_path))
    for variable in ("APPDATA", "LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"):
        if os.environ.get(variable):
            candidates.append(Path(os.environ[variable]) / "Telegram Desktop/Telegram.exe")
    try:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, r"Software\Microsoft\Windows\CurrentVersion\App Paths\Telegram.exe") as key:
                    candidates.append(Path(winreg.QueryValue(key, None)))
            except OSError:
                pass
    except ImportError:
        pass
    for candidate in candidates:
        if candidate.is_file() and candidate.suffix.casefold() == ".exe":
            return candidate.resolve()
    # Running Telegram may belong to a migrated profile with a different home path.
    command = "[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false); @(Get-Process -Name Telegram -ErrorAction SilentlyContinue | ForEach-Object {$_.Path}) | ConvertTo-Json -Compress"
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                                capture_output=True, encoding="utf-8", timeout=8,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        paths = json.loads(result.stdout.lstrip("\ufeff")) if result.stdout.strip() else []
        for item in paths if isinstance(paths, list) else [paths]:
            if item and Path(item).is_file() and Path(item).name.casefold() == "telegram.exe":
                return Path(item).resolve()
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return None


def ensure_native_config(settings, path=None):
    path = path or USER_DIR / "kernel.json"
    config = json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else {"enable_actions": True, "applications": {}}
    if not isinstance(config, dict) or not isinstance(config.get("applications", {}), dict):
        raise ValueError("Некорректная локальная конфигурация ядра")
    config.setdefault("applications", {})
    current = config["applications"].get("telegram", {}).get("path")
    if settings.telegram_path or not current or not Path(current).is_file():
        telegram = discover_telegram(settings)
        if telegram:
            config["applications"]["telegram"] = {"path": str(telegram), "args": [], "hidden": False}
    config["enable_actions"] = True
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def configure(settings):
    print("Ключ сохранится локально вне Git. Можно вместо этого заполнить .env в папке проекта.")
    key = getpass.getpass("OpenRouter API key (скрытый ввод; Enter — оставить текущий): ").strip() or settings.api_key
    model = input(f"Модель [{settings.model}]: ").strip() or settings.model
    city = input(f"Город [{settings.city or 'автоматически'}]: ").strip() or settings.city
    for value in (key, model, city):
        if "\n" in value or "\r" in value:
            raise ValueError("Значение должно занимать одну строку")
    from .config import read_env
    path = settings.root / ".env"
    values = read_env(path)
    values.update(OPENROUTER_API_KEY=key, OPENROUTER_MODEL=model, JARVIS_CITY=city)
    path.write_text("".join(f"{name}={value}\n" for name, value in values.items()), encoding="utf-8")
    print(f"Настройки сохранены: {path}. Этот файл исключён из Git.")
