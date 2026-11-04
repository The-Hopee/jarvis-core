"""Windowless Task Scheduler entry point with bounded local UTF-8 logs."""
import logging
from logging.handlers import RotatingFileHandler
import os
import sys

from .config import USER_DIR


class LogStream:
    encoding = "utf-8"

    def __init__(self, logger, level):
        self.logger, self.level = logger, level
        self.pending = ""

    def write(self, text):
        self.pending += text
        while "\n" in self.pending:
            line, self.pending = self.pending.split("\n", 1)
            if line.rstrip():
                self.logger.log(self.level, line.rstrip())
        return len(text)

    def flush(self):
        if self.pending.strip():
            self.logger.log(self.level, self.pending.rstrip())
        self.pending = ""

    def isatty(self):
        return False

    def reconfigure(self, **_kwargs):
        pass


def main():
    directory = USER_DIR / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("jarvis.background")
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(directory / "assistant.log", maxBytes=2 * 1024 * 1024,
                                  backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    stdout, stderr, stdin = sys.stdout, sys.stderr, sys.stdin
    sys.stdout, sys.stderr = LogStream(logger, logging.INFO), LogStream(logger, logging.ERROR)
    # pythonw starts without console streams. Popen still needs a valid stdin source
    # for a few Windows helpers; the assistant's microphone is independent of stdin.
    null_input = open(os.devnull, "r", encoding="utf-8")
    sys.stdin = null_input
    code = 1
    try:
        logger.info("Starting Jarvis background process (pid=%s)", os.getpid())
        from .__main__ import main as run_assistant
        code = run_assistant()
        return code
    except Exception:
        logger.exception("Jarvis background process failed")
        return 1
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        logger.info("Jarvis background process exited (code=%s)", code)
        sys.stdout, sys.stderr, sys.stdin = stdout, stderr, stdin
        null_input.close()
        logger.removeHandler(handler)
        handler.close()


if __name__ == "__main__":
    raise SystemExit(main())
