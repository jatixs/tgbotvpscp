import os
import shutil
import sys
import tempfile
import types
import unittest
from base64 import b64encode
from unittest.mock import MagicMock, patch

os.environ.setdefault("DATA_ENCRYPTION_KEY", b64encode(b"0" * 32).decode())
os.environ.setdefault("TG_BOT_TOKEN", "123456789:TEST_BOT_TOKEN")
os.environ.setdefault("TG_ADMIN_ID", "12345")

modules_to_mock = [
    "aiohttp", "aiohttp.web", "argon2", "argon2.exceptions", "aiosqlite",
    "requests", "PIL", "PIL.Image", "qrcode",
    "netifaces", "sentry_sdk", "yaml", "docker", "asyncssh", "tortoise",
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

from core import config, shared_state  # noqa: E402
from modules import traffic  # noqa: E402


class TrafficModuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="traffic_test_")
        cls.orig_backup_dir = config.TRAFFIC_BACKUP_DIR
        cls.orig_monitors_file = traffic.TRAFFIC_MONITORS_FILE
        config.TRAFFIC_BACKUP_DIR = os.path.join(cls.test_dir, "backups")
        traffic.TRAFFIC_MONITORS_FILE = os.path.join(cls.test_dir, "active_monitors.json")
        os.makedirs(config.TRAFFIC_BACKUP_DIR, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        config.TRAFFIC_BACKUP_DIR = cls.orig_backup_dir
        traffic.TRAFFIC_MONITORS_FILE = cls.orig_monitors_file
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setUp(self):
        shared_state.TRAFFIC_MESSAGE_IDS.clear()
        traffic.TRAFFIC_OFFSET["rx"] = 0
        traffic.TRAFFIC_OFFSET["tx"] = 0
        traffic._state_loaded = False
        if os.path.exists(traffic.TRAFFIC_MONITORS_FILE):
            os.remove(traffic.TRAFFIC_MONITORS_FILE)

    def test_active_monitors_save_and_load(self):
        monitors = {12345: 9988, 67890: 1122}
        traffic._save_active_monitors(monitors)

        loaded = traffic._load_active_monitors()
        self.assertEqual(loaded, monitors)

    def test_save_current_traffic_backup(self):
        mock_counters = MagicMock(bytes_recv=5000, bytes_sent=8000)
        with patch("psutil.net_io_counters", return_value=mock_counters), patch("psutil.boot_time", return_value=1700000000.0):
            traffic.TRAFFIC_OFFSET["rx"] = 1000
            traffic.TRAFFIC_OFFSET["tx"] = 2000
            traffic.save_current_traffic_backup()

        backups = os.listdir(config.TRAFFIC_BACKUP_DIR)
        self.assertTrue(len(backups) >= 1)

    def test_get_current_traffic_total_auto_loads_state(self):
        mock_counters = MagicMock(bytes_recv=10000, bytes_sent=20000)
        with patch("psutil.net_io_counters", return_value=mock_counters):
            traffic._state_loaded = False
            rx, tx = traffic.get_current_traffic_total()
            self.assertTrue(traffic._state_loaded)
            self.assertGreaterEqual(rx, 10000)
            self.assertGreaterEqual(tx, 20000)


if __name__ == "__main__":
    unittest.main()
