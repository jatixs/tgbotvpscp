import os
import sys
import tempfile
import shutil
import types
import unittest
from base64 import b64encode
from unittest.mock import patch, MagicMock

os.environ.setdefault("DATA_ENCRYPTION_KEY", b64encode(b"0" * 32).decode())
os.environ.setdefault("TG_BOT_TOKEN", "123456789:TEST_BOT_TOKEN")
os.environ.setdefault("TG_ADMIN_ID", "12345")

modules_to_mock = [
    "aiohttp", "aiohttp.web", "argon2", "argon2.exceptions", "aiosqlite",
    "requests", "PIL", "PIL.Image", "qrcode",
    "netifaces", "sentry_sdk", "yaml", "docker", "docker.client", "docker.errors",
    "asyncssh", "tortoise",
    "aiogram", "aiogram.filters", "aiogram.fsm", "aiogram.fsm.context",
    "aiogram.fsm.state", "aiogram.fsm.storage", "aiogram.fsm.storage.memory",
    "aiogram.types", "aiogram.exceptions",
]

for m in modules_to_mock:
    if m not in sys.modules:
        mod = MagicMock()
        mod.__path__ = []
        mod.__spec__ = types.SimpleNamespace(name=m, origin=None, submodule_search_locations=[])
        sys.modules[m] = mod

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import watchdog


class TestWatchdogCrashAlert(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.env_file = os.path.join(self.test_dir, ".env")
        with open(self.env_file, "w") as f:
            f.write("TG_BOT_TOKEN=123456:FAKE_TOKEN\nTG_ADMIN_ID=1234567\nDEFAULT_LANGUAGE=ru\n")

        self.config_dir = os.path.join(self.test_dir, "config")
        os.makedirs(self.config_dir, exist_ok=True)

        self.logs_dir = os.path.join(self.test_dir, "logs", "bot")
        os.makedirs(self.logs_dir, exist_ok=True)
        self.bot_log = os.path.join(self.logs_dir, "bot.log")
        with open(self.bot_log, "w") as f:
            f.write("ERROR:root:Traceback (most recent call last):\n  File 'test.py', line 10\nZeroDivisionError: division by zero\n")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_planned_restart_flag_ignores_crash_alert(self):
        """If restart_flag.txt exists, run_crash_alert_oneshot exits without sending crash alert."""
        restart_flag = os.path.join(self.config_dir, "restart_flag.txt")
        with open(restart_flag, "w") as f:
            f.write("123:456")

        with patch("os.path.dirname", return_value=self.test_dir), \
             patch("http.client.HTTPSConnection") as mock_conn_cls:
            with self.assertRaises(SystemExit) as cm:
                watchdog.run_crash_alert_oneshot()
            self.assertEqual(cm.exception.code, 0)
            mock_conn_cls.assert_not_called()

    def test_unplanned_crash_sends_telegram_alert(self):
        """If no flag exists, run_crash_alert_oneshot extracts log error and sends Telegram alert."""
        with patch("os.path.dirname", return_value=self.test_dir), \
             patch("http.client.HTTPSConnection") as mock_conn_cls:
            mock_conn = MagicMock()
            mock_conn_cls.return_value = mock_conn

            with self.assertRaises(SystemExit) as cm:
                watchdog.run_crash_alert_oneshot()

            self.assertEqual(cm.exception.code, 0)
            mock_conn_cls.assert_called_once_with("api.telegram.org", timeout=10)
            mock_conn.request.assert_called_once()
            args, kwargs = mock_conn.request.call_args
            method, path = args[0], args[1]
            body = kwargs.get("body") if "body" in kwargs else args[2]
            self.assertEqual(method, "POST")
            self.assertIn("123456:FAKE_TOKEN", path)
            body_str = body.decode("utf-8") if isinstance(body, bytes) else body
            self.assertIn("ZeroDivisionError", body_str)
            self.assertIn("Аварийная остановка", body_str)


if __name__ == "__main__":
    unittest.main()
