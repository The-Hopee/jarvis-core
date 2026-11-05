import argparse
from contextlib import ExitStack
import importlib.metadata
import json
import sys

from .assistant import Assistant,Turn
from .config import Settings
from .http import ServiceError
from .ipc import KernelClient, KernelError
from .openrouter import OpenRouterClient
from .services import LocalServices
from .setup import configure, ensure_native_config
from .speech import Speaker
from .tools import ToolRegistry
from .runtime import AlreadyRunning, RuntimeOwner, is_running
from .interaction import run_turn
from .progress import ProgressFeedback
from .telemetry import mark
from .jobs import GuardedKernel,JobCancelled


def display(turn):
    print("Джарвис: " + turn.text, flush=True)
    if turn.warning:
        print("[Сервис] " + turn.warning, file=sys.stderr)
    for record in turn.tools:
        output = record["output"]
        if record['name'] in {'create_document','fill_document','open_document','background_artifact'} and output.get('ok') and output.get('result',{}).get('path'):
            print('Файл: '+output['result']['path'],flush=True)
        if record['name'] == 'search_vk_music' and output.get('ok'):
            for index, track in enumerate(output['result'].get('tracks', []), 1):
                print(f"  VK {index}. {track['artist']} — {track['title']}")
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
    group.add_argument('--privacy-report',action='store_true',help='счётчики разрешённых и заблокированных обращений без содержимого данных')
    group.add_argument('--privacy-check',action='store_true',help='локальная проверка защиты с вымышленными данными, без сети')
    group.add_argument("--list-mics", action="store_true", help="список микрофонов")
    group.add_argument("--download-model", action="store_true", help="скачать локальную русскую ASR-модель (~45 MB)")
    group.add_argument("--configure", action="store_true", help="локально ввести API-ключ и город")
    group.add_argument("--speak", help="проверить озвучивание указанной фразой")
    group.add_argument("--voice-previews", action="store_true", help="создать три образца голоса: normal, deep, cinematic")
    group.add_argument("--download-voice", action="store_true", help="установить локальную русскую нейромодель голоса")
    group.add_argument("--telegram-login", action="store_true", help="локально подключить Telegram API")
    group.add_argument("--vk-login", action="store_true", help="войти в VK в отдельном браузере Джарвиса")
    group.add_argument('--prepare-status-voice', action='store_true', help='однократно подготовить короткие статусы выбранным голосом')
    group.add_argument('--latency-report', action='store_true', help='показать обезличенные замеры задержек')
    group.add_argument('--jobs',action='store_true',help='состояния сохранённых фоновых задач')
    group.add_argument('--cancel-job',help='запросить отмену задачи по номеру или ID')
    parser.add_argument("--mute", action="store_true", help="выводить ответы только текстом")
    parser.add_argument('--latency-source', choices=('voice','text'), help='показывать метрики только голосовых или текстовых обращений')
    arguments = parser.parse_args()
    try:
        settings = Settings.load()
        if arguments.jobs or arguments.cancel_job:
            from .jobs import JobStore
            store=JobStore()
            value=store.cancel(arguments.cancel_job) if arguments.cancel_job else store.recent(16)
            print(json.dumps(value,ensure_ascii=False,indent=2))
            return 0
        if arguments.privacy_check:
            from .privacy_check import main as privacy_check
            return privacy_check()
        if arguments.privacy_report:
            from .privacy import report
            print(json.dumps(report(),ensure_ascii=False,indent=2));return 0
        if arguments.latency_report:
            from .telemetry import LOG_PATH, report
            paths = [LOG_PATH.with_name(LOG_PATH.name + '.' + str(n)) for n in (3, 2, 1)] + [LOG_PATH]
            print(json.dumps(report(paths, source=arguments.latency_source), ensure_ascii=False, indent=2))
            return 0
        if arguments.prepare_status_voice:
            from .progress import prepare_status_voice
            print(json.dumps({'cached_status_files': prepare_status_voice(settings)}, ensure_ascii=False, indent=2))
            return 0
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
            if not arguments.doctor:
                runtime = resources.enter_context(RuntimeOwner())
            kernel = resources.enter_context(KernelClient(settings.executable, config))
            ready = kernel.call("ping")["result"]
            if arguments.doctor:
                packages = {}
                for package in ("vosk", "sounddevice", "edge-tts", "jsonschema"):
                    packages[package] = importlib.metadata.version(package)
                print(json.dumps({"native": ready, "voice_running": is_running(), "openrouter_key_present": bool(settings.api_key),
                                  "privacy_mode":settings.privacy_mode,"chat_cloud_allowed":False,"allow_cloud_asr":settings.allow_cloud_asr,
                                  "model": settings.model, "tts": settings.tts, "voice": settings.voice,
                                  "voice_preset": settings.voice_preset,
                                  "local_speaker": settings.local_speaker,
                                  "asr": settings.asr, "conversation_seconds": settings.conversation_seconds,
                                  "asr_model": settings.asr_model, "tts_model": settings.tts_model,
                                  "progress_enabled": settings.progress_enabled,
                                  "status_clips_present": sum((speaker.status_directory / (kind + '.mp3')).is_file() or (speaker.status_directory / (kind + '.wav')).is_file() for kind in ('asr','model','tool','tts')),
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
            tools_kernel=GuardedKernel(kernel,runtime.stopped) if runtime is not None else kernel
            services = LocalServices(settings, tools_kernel)
            registry = ToolRegistry(tools_kernel, services,cancelled=runtime.stopped if runtime else None)
            resources.callback(registry.close)
            client = OpenRouterClient(settings.api_key, settings.model) if settings.api_key else None
            from .routing import Router
            assistant = Assistant(registry, client,stopped=runtime.stopped if runtime else None,router=Router(settings))
            if not settings.api_key:
                print("[Настройка] Ключ OpenRouter пока не задан: работают базовые локальные команды. Добавьте OPENROUTER_API_KEY в .env для свободного диалога.", file=sys.stderr)
            if arguments.once is not None:
                turn = run_turn(assistant, speaker, arguments.once, display=display)
                return 1 if turn.tools and any(not record["output"].get("ok") for record in turn.tools) else 0
            from .home_jobs import HomeJobs
            jobs=resources.enter_context(HomeJobs(tools_kernel,registry.vk,settings,stopped=runtime.stopped if runtime else None))
            registry.home_jobs=jobs
            if arguments.text:
                print("Текстовый режим. Для выхода: /exit. Голосовой ответ включён, если не задан --mute.")
                while True:
                    text = input("Ты: ").strip()
                    if text in {"/exit", "/quit"}:
                        break
                    if not text:
                        continue
                    for notification in jobs.drain(assistant):display(notification);speaker.speak(notification.text)
                    control=jobs.control(text,assistant)
                    background=jobs.background_text(text)
                    if control:display(control);speaker.speak(control.text)
                    elif background:
                        try:
                            job=jobs.submit(background,assistant)
                            print(f"Задача {job['number']} принята в очередь.",flush=True)
                            speaker.speak('Да, сэр.')
                        except ServiceError as exc:print(str(exc),flush=True)
                    else:run_turn(assistant, speaker, text, display=display)
            else:
                from .voice import VoiceInput
                voice = VoiceInput(settings)
                print("Голосовой режим: скажите «Джарвис, состояние машины». Выход: «Джарвис, выход» или Ctrl+C.", flush=True)
                while not runtime.stopped():
                    for notification in jobs.drain(assistant):
                        display(notification)
                        if not runtime.stopped():speaker.speak(notification.text,stopped=runtime.stopped)
                        music=registry.vk.music_active if registry.vk.music_active is not None else assistant.conversation.music_playing
                        voice.after_response(0 if music else None)
                    print("[Микрофон] Можно продолжать без имени…" if voice.gate.active() else "[Микрофон] Слушаю обращение «Джарвис»…", flush=True)
                    feedback = ProgressFeedback(speaker, delay=settings.progress_delay,
                                                enabled=settings.progress_enabled, stopped=runtime.stopped)
                    try:
                        # Classify the completed command before enabling spoken
                        # progress; an ASR acceptance alone says nothing about it.
                        text = voice.next_command(stop_requested=runtime.stopped,interrupt_requested=jobs.store.has_notifications)
                        if text is None:
                            if voice.last_interrupted:continue
                            break
                        trace = voice.last_trace
                        with trace.activate():
                            if text.casefold().strip(" .!?,") in {"выход", "завершить работу", "до свидания"}:
                                mark('answer_ready')
                                speaker.speak("До связи.", before_playback=feedback.stop)
                                break
                            if text.casefold().strip(" .!?,") in {"спасибо хватит", "хватит", "тихий режим", "пока", "отбой", "спящий режим"}:
                                voice.sleep()
                                mark('answer_ready')
                                speaker.speak("Хорошо. Позови, когда понадоблюсь.", before_playback=feedback.stop)
                                assistant.reset_conversation()
                                continue
                        print("Ты: " + (text or "Джарвис"), flush=True)
                        control=jobs.control(text,assistant)
                        background=jobs.background_text(text)
                        if control or background:
                            with trace.activate():
                                feedback.stop()
                                if control:
                                    display(control);speaker.speak(control.text,stopped=runtime.stopped)
                                else:
                                    try:
                                        job=jobs.submit(background,assistant)
                                        print(f"Задача {job['number']} принята в очередь.",flush=True)
                                        mark('job_accepted');speaker.speak('Да, сэр.',stopped=runtime.stopped)
                                    except ServiceError as exc:speaker.speak(str(exc),stopped=runtime.stopped)
                            if background:voice.after_response(0);continue
                        else:run_turn(assistant, speaker, text, trace=trace, feedback=feedback, display=display, stopped=runtime.stopped)
                        if not runtime.stopped():
                            playing_music = registry.vk.music_active if registry.vk.music_active is not None else assistant.conversation.music_playing
                            voice.after_response((8 if not text else 0) if playing_music else None)
                    finally:
                        feedback.stop()
                        if voice.last_trace is not None:
                            voice.last_trace.finish('cancelled' if runtime.stopped() else 'completed')
        return 0
    except AlreadyRunning as exc:
        print(str(exc))
        return 0
    except (KeyboardInterrupt, EOFError,JobCancelled):
        print("\nДжарвис остановлен.")
        return 0
    except (KernelError, ServiceError, RuntimeError, OSError, ValueError) as exc:
        print("Ошибка: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
