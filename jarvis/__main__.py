import argparse
from contextlib import ExitStack
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
from .runtime import AlreadyRunning, RuntimeOwner, is_running


def display(turn):
    print("Джарвис: " + turn.text, flush=True)
    if turn.warning:
        print("[Сервис] " + turn.warning, file=sys.stderr)
    for record in turn.tools:
        output = record["output"]
        if record["name"] in {"open_youtube_video", "search_youtube"} and output.get("ok"):
            result = output["result"]
            if result.get("url"):
                print("  Видео: " + result["url"])
            for index, video in enumerate(result.get("videos", []), 1):
                print(f"  {index}. {video['title']}: {video['url']}")
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
    group.add_argument("--voice-previews", action="store_true", help="создать три образца голоса: normal, deep, cinematic")
    group.add_argument("--download-voice", action="store_true", help="установить локальную русскую нейромодель голоса")
    group.add_argument("--telegram-login", action="store_true", help="локально подключить Telegram API")
    group.add_argument("--vk-login", action="store_true", help="войти в VK в отдельном браузере Джарвиса")
    parser.add_argument("--mute", action="store_true", help="выводить ответы только текстом")
    arguments = parser.parse_args()
    try:
        settings = Settings.load()
        if arguments.vk_login:
            from .vk_browser import login
            login()
            return 0
        if arguments.telegram_login:
            from .telegram_api import login
            login(settings)
            return 0
        if arguments.download_voice:
            from .tts_local import download_model
            print(download_model())
            return 0
        if arguments.voice_previews:
            from .speech import voice_previews
            print(json.dumps(voice_previews(settings), ensure_ascii=False, indent=2))
            return 0
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
        with ExitStack() as resources:
            runtime = None
            if not arguments.doctor and arguments.once is None and not arguments.text:
                runtime = resources.enter_context(RuntimeOwner())
            kernel = resources.enter_context(KernelClient(settings.executable, config))
            ready = kernel.call("ping")["result"]
            if arguments.doctor:
                packages = {}
                for package in ("vosk", "sounddevice", "edge-tts", "jsonschema"):
                    packages[package] = importlib.metadata.version(package)
                print(json.dumps({"native": ready, "voice_running": is_running(), "openrouter_key_present": bool(settings.api_key),
                                  "model": settings.model, "tts": settings.tts, "voice": settings.voice,
                                  "voice_preset": settings.voice_preset,
                                  "local_speaker": settings.local_speaker,
                                  "asr": settings.asr, "conversation_seconds": settings.conversation_seconds,
                                  "asr_model": settings.asr_model, "tts_model": settings.tts_model,
                                  "voice_reference_present": bool(settings.voice_reference),
                                  "voice_samples_configured": bool(settings.voice_samples),
                                  "elevenlabs_key_present": bool(settings.elevenlabs_api_key),
                                  "cloud_voice_selected": bool(settings.elevenlabs_voice_id),
                                  "document_roots": [str(p) for p in settings.document_roots],
                                  "telegram_api_configured": bool(settings.telegram_api_id and settings.telegram_api_hash),
                                  "vosk_model_installed": (settings.model_path / "am/final.mdl").is_file(),
                                  "location_mode": "coordinates" if settings.latitude is not None else "city" if settings.city else "Windows then approximate IP",
                                  "applications": kernel.call("list_apps")["result"]["applications"], "packages": packages}, ensure_ascii=False, indent=2))
                return 0
            services = LocalServices(settings, kernel)
            registry = ToolRegistry(kernel, services)
            resources.callback(registry.close)
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
                while not runtime.stopped():
                    print("[Микрофон] Можно продолжать без имени…" if voice.gate.active() else "[Микрофон] Слушаю обращение «Джарвис»…", flush=True)
                    text = voice.next_command(stop_requested=runtime.stopped)
                    if text is None:
                        break
                    if text.casefold().strip(" .!?,") in {"выход", "завершить работу", "до свидания"}:
                        speaker.speak("До связи.")
                        break
                    if text.casefold().strip(" .!?,") in {"спасибо хватит", "хватит", "тихий режим", "пока", "отбой", "спящий режим"}:
                        voice.sleep()
                        speaker.speak("Хорошо. Позови, когда понадоблюсь.")
                        assistant.reset_conversation()
                        continue
                    print("Ты: " + (text or "Джарвис"), flush=True)
                    turn = assistant.respond(text)
                    display(turn)
                    if not runtime.stopped():
                        speaker.speak(turn.text)
                        voice.after_response()
        return 0
    except AlreadyRunning as exc:
        print(str(exc))
        return 0
    except (KeyboardInterrupt, EOFError):
        print("\nДжарвис остановлен.")
        return 0
    except (KernelError, ServiceError, RuntimeError, OSError, ValueError) as exc:
        print("Ошибка: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
