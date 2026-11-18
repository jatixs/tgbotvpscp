import os
import shutil
import tempfile
import unittest
from base64 import b64encode
from unittest.mock import MagicMock, patch

from tests.support import AIOGRAM_DEPENDENCIES, CORE_DEPENDENCIES, mock_optional_modules


class TrafficModuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("DATA_ENCRYPTION_KEY", b64encode(b"0" * 32).decode())
        os.environ.setdefault("TG_BOT_TOKEN", "123456789:TEST_BOT_TOKEN")
        os.environ.setdefault("TG_ADMIN_ID", "12345")

        mock_optional_modules((*CORE_DEPENDENCIES, *AIOGRAM_DEPENDENCIES))

        from core import config, shared_state
        from modules import traffic

        cls.config = config
        cls.shared_state = shared_state
        cls.traffic = traffic

        cls.test_dir = tempfile.mkdtemp(prefix="traffic_test_")
        cls.orig_backup_dir = cls.config.TRAFFIC_BACKUP_DIR
        cls.orig_monitors_file = cls.traffic.TRAFFIC_MONITORS_FILE
        cls.config.TRAFFIC_BACKUP_DIR = os.path.join(cls.test_dir, "backups")
        cls.traffic.TRAFFIC_MONITORS_FILE = os.path.join(cls.test_dir, "active_monitors.json")
        os.makedirs(cls.config.TRAFFIC_BACKUP_DIR, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        cls.config.TRAFFIC_BACKUP_DIR = cls.orig_backup_dir
        cls.traffic.TRAFFIC_MONITORS_FILE = cls.orig_monitors_file
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setUp(self):
        self.shared_state.TRAFFIC_MESSAGE_IDS.clear()
        self.traffic.TRAFFIC_OFFSET["rx"] = 0
        self.traffic.TRAFFIC_OFFSET["tx"] = 0
        self.traffic._state_loaded = False
        if os.path.exists(self.traffic.TRAFFIC_MONITORS_FILE):
            os.remove(self.traffic.TRAFFIC_MONITORS_FILE)

    def test_active_monitors_save_and_load(self):
        monitors = {12345: 9988, 67890: 1122}
        self.traffic._save_active_monitors(monitors)

        loaded = self.traffic._load_active_monitors()
        self.assertEqual(loaded, monitors)

    def test_save_current_traffic_backup(self):
        mock_counters = MagicMock(bytes_recv=5000, bytes_sent=8000)
        with patch("psutil.net_io_counters", return_value=mock_counters), patch("psutil.boot_time", return_value=1700000000.0):
            self.traffic.TRAFFIC_OFFSET["rx"] = 1000
            self.traffic.TRAFFIC_OFFSET["tx"] = 2000
            self.traffic.save_current_traffic_backup()

        backups = os.listdir(self.config.TRAFFIC_BACKUP_DIR)
        self.assertTrue(len(backups) >= 1)

    def test_get_current_traffic_total_auto_loads_state(self):
        mock_counters = MagicMock(bytes_recv=10000, bytes_sent=20000)
        with patch("psutil.net_io_counters", return_value=mock_counters):
            self.traffic._state_loaded = False
            rx, tx = self.traffic.get_current_traffic_total()
            self.assertTrue(self.traffic._state_loaded)
            self.assertGreaterEqual(rx, 10000)
            self.assertGreaterEqual(tx, 20000)


if __name__ == "__main__":
    unittest.main()
