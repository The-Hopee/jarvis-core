"""Manage only this project's session-local assistant; never kill a PID by name."""
import argparse
import json
import sys

from .config import USER_DIR
from .runtime import is_running, request_stop


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["status", "stop", "wait-running", "wait-stopped"])
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()
    if not 0 <= args.timeout <= 120:
        parser.error("timeout must be between 0 and 120 seconds")
    if args.action == "status":
        print(json.dumps({"running": is_running(), "log": str(USER_DIR / "logs/assistant.log")}, ensure_ascii=False))
        return 0
    if args.action == "stop":
        stopped = request_stop(timeout=args.timeout)
        print("Джарвис остановлен." if stopped else "Остановка запрошена; текущая команда ещё завершается.")
        return 0 if stopped else 1
    import time
    expected = args.action == "wait-running"
    deadline = time.monotonic() + args.timeout
    while is_running() != expected:
        if time.monotonic() >= deadline:
            print("Истекло время ожидания состояния Джарвиса.")
            return 1
        time.sleep(0.1)
    print("Джарвис работает." if expected else "Джарвис остановлен.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
