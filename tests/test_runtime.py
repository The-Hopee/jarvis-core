import io
import logging
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis.background import LogStream
from jarvis.runtime import AlreadyRunning, RuntimeOwner, is_running, request_stop

ROOT = Path(__file__).resolve().parents[1]


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.name = 'Local\\Jarvis.RuntimeTest.' + uuid.uuid4().hex

    def test_status_and_remote_stop_release_handles(self):
        self.assertFalse(is_running(self.name))
        results = []
        with RuntimeOwner(self.name) as owner:
            self.assertTrue(is_running(self.name))
            self.assertFalse(owner.stopped())
            thread = threading.Thread(target=lambda: results.append(request_stop(self.name, timeout=3)))
            thread.start()
            deadline = time.monotonic() + 2
            while not owner.stopped() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(owner.stopped())
        thread.join(timeout=4)
        self.assertEqual(results, [True])
        self.assertFalse(is_running(self.name))
        self.assertTrue(request_stop(self.name, timeout=0))

    def test_second_process_cannot_acquire_active_instance(self):
        code = ('from jarvis.runtime import RuntimeOwner, AlreadyRunning\n'
                'try:\n'
                f'    with RuntimeOwner({self.name!r}):\n'
                '        raise SystemExit(3)\n'
                'except AlreadyRunning:\n'
                '    print("already-running")\n')
        with RuntimeOwner(self.name):
            child = subprocess.run([sys.executable, '-c', code], cwd=ROOT, text=True,
                                   capture_output=True, timeout=10)
            self.assertEqual(child.returncode, 0, child.stderr)
            self.assertIn('already-running', child.stdout)

    def test_crashed_owner_does_not_leave_a_stale_lock(self):
        code = ('from jarvis.runtime import RuntimeOwner\n'
                'import os\n'
                f'with RuntimeOwner({self.name!r}):\n'
                '    os._exit(4)\n')
        child = subprocess.run([sys.executable, '-c', code], cwd=ROOT, timeout=10)
        self.assertEqual(child.returncode, 4)
        with RuntimeOwner(self.name) as owner:
            self.assertFalse(owner.stopped())
        self.assertFalse(is_running(self.name))

    def test_background_log_stream_preserves_partial_utf8_lines(self):
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        logger = logging.getLogger(self.name)
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        try:
            stream = LogStream(logger, logging.INFO)
            stream.write('Джар')
            stream.write('вис\nСлушаю')
            stream.flush()
            self.assertEqual(output.getvalue(), 'Джарвис\nСлушаю\n')
        finally:
            logger.removeHandler(handler)
            handler.close()


if __name__ == '__main__':
    unittest.main()
