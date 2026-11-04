import argparse
import importlib.metadata
import json
import sys

from .assistant import Assistant
from .config import Settings
from .http import ServiceError
from .ipc import KernelClient, KernelError
from .openrouter import OpenRouterClient
from .services import LocalServices
from .setup import configure, ensure_native_config
from .speech import Speaker
from .tools import ToolRegistry


def display(turn):
    print("Джарвис: " + turn.text, flush=True)
    if turn.warning:
        print("[Сервис] " + turn.warning, file=sys.stderr)
    for record in turn.tools:
        output = record["output"]
        if record["name"] == "find_places" and output.get("ok"):
            if output["result"].get("search_url"):
                print("  Поиск на карте: " + output["result"]["search_url"])
            for place in output["result"].get("places", []):
                print("  " + place["name"] + ": " + place["map_url"])
            if output["result"].get("attribution"):
                print("  " + output["result"]["attribution"])


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Джарвис — домашний голосовой помощник")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--text", action="store_true", help="текстовый ввод с голосовым ответом")
    group.add_argument("--once", help="выполнить одну текстовую команду")
    group.add_argument("--doctor", action="store_true", help="проверка установки без вызова LLM")
    group.add_argument("--list-mics", action="store_true", help="список микрофонов")
    group.add_argument("--download-model", action="store_true", help="скачать локальную русскую ASR-модель (~45 MB)")
    group.add_argument("--configure", action="store_true", help="локально ввести API-ключ и город")
    group.add_argument("--speak", help="проверить озвучивание указанной фразой")
    parser.add_argument("--mute", action="store_true", help="выводить ответы только текстом")
    arguments = parser.parse_args()
    try:
        settings = Settings.load()
        if arguments.configure:
            configure(settings)
            return 0
        if arguments.download_model:
            from .voice import download_model
            print("Загружаю русскую модель распознавания с alphacephei.com…", flush=True)
            print(download_model(settings.model_path))
            return 0
        if arguments.list_mics:
            import sounddevice
            for index, device in enumerate(sounddevice.query_devices()):
                if device["max_input_channels"]:
                    print(f"{index}: {device['name']}")
            return 0
        speaker = Speaker(settings, arguments.mute)
        if arguments.speak:
            speaker.speak(arguments.speak)
            return 0
        config = ensure_native_config(settings)
        with KernelClient(settings.executable, config) as kernel:
            ready = kernel.call("ping")["result"]
            if arguments.doctor:
                packages = {}
                for package in ("vosk", "sounddevice", "edge-tts", "jsonschema"):
                    packages[package] = importlib.metadata.version(package)
                print(json.dumps({"native": ready, "openrouter_key_present": bool(settings.api_key),
                                  "model": settings.model, "tts": settings.tts, "voice": settings.voice,
                                  "vosk_model_installed": (settings.model_path / "am/final.mdl").is_file(),
                                  "location_mode": "coordinates" if settings.latitude is not None else "city" if settings.city else "Windows then approximate IP",
                                  "applications": kernel.call("list_apps")["result"]["applications"], "packages": packages}, ensure_ascii=False, indent=2))
                return 0
            services = LocalServices(settings, kernel)
            registry = ToolRegistry(kernel, services)
            client = OpenRouterClient(settings.api_key, settings.model) if settings.api_key else None
            assistant = Assistant(registry, client)
            if not settings.api_key:
                print("[Настройка] Ключ OpenRouter пока не задан: работают базовые локальные команды. Добавьте OPENROUTER_API_KEY в .env для свободного диалога.", file=sys.stderr)
            if arguments.once is not None:
                turn = assistant.respond(arguments.once)
                display(turn)
                speaker.speak(turn.text)
                return 1 if turn.tools and any(not record["output"].get("ok") for record in turn.tools) else 0
            if arguments.text:
                print("Текстовый режим. Для выхода: /exit. Голосовой ответ включён, если не задан --mute.")
                while True:
                    text = input("Ты: ").strip()
                    if text in {"/exit", "/quit"}:
                        break
                    if not text:
                        continue
                    turn = assistant.respond(text)
                    display(turn)
                    speaker.speak(turn.text)
            else:
                from .voice import VoiceInput
                voice = VoiceInput(settings)
                print("Голосовой режим: скажите «Джарвис, состояние машины». Выход: «Джарвис, выход» или Ctrl+C.", flush=True)
                while True:
                    print("[Микрофон] Слушаю обращение «Джарвис»…", flush=True)
                    text = voice.next_command()
                    if text.casefold() in {"выход", "завершить работу", "до свидания"}:
                        speaker.speak("До связи.")
                        break
                    print("Ты: " + (text or "Джарвис"), flush=True)
                    turn = assistant.respond(text)
                    display(turn)
                    speaker.speak(turn.text)
        return 0
    except (KeyboardInterrupt, EOFError):
        print("\nДжарвис остановлен.")
        return 0
    except (KernelError, ServiceError, RuntimeError, OSError, ValueError) as exc:
        print("Ошибка: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
