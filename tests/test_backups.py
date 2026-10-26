import os
import shutil
import sys
import tempfile
import types
import unittest
import json
import time
import asyncio
from base64 import b64encode
from unittest.mock import MagicMock, patch, AsyncMock

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

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core import config
from modules import backups


class TestBackups(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.orig_config_dir = config.CONFIG_DIR
        self.orig_log_dir = config.LOG_DIR
        self.orig_traffic_backup = config.TRAFFIC_BACKUP_DIR
        self.orig_config_backup = config.CONFIG_BACKUP_DIR
        self.orig_logs_backup = config.LOGS_BACKUP_DIR
        self.orig_nodes_backup = config.NODES_BACKUP_DIR

        config.CONFIG_DIR = os.path.join(self.test_dir, "config")
        config.LOG_DIR = os.path.join(self.test_dir, "logs")
        config.TRAFFIC_BACKUP_DIR = os.path.join(self.test_dir, "backups", "traffic")
        config.CONFIG_BACKUP_DIR = os.path.join(self.test_dir, "backups", "config")
        config.LOGS_BACKUP_DIR = os.path.join(self.test_dir, "backups", "logs")
        config.NODES_BACKUP_DIR = os.path.join(self.test_dir, "backups", "nodes")

        for d in [
            config.CONFIG_DIR,
            config.LOG_DIR,
            config.TRAFFIC_BACKUP_DIR,
            config.CONFIG_BACKUP_DIR,
            config.LOGS_BACKUP_DIR,
            config.NODES_BACKUP_DIR,
        ]:
            os.makedirs(d, exist_ok=True)

        # Update BACKUP_TYPES to point to test paths
        backups.BACKUP_TYPES["traffic"]["dir"] = config.TRAFFIC_BACKUP_DIR
        backups.BACKUP_TYPES["config"]["dir"] = config.CONFIG_BACKUP_DIR
        backups.BACKUP_TYPES["logs"]["dir"] = config.LOGS_BACKUP_DIR
        backups.BACKUP_TYPES["nodes"]["dir"] = config.NODES_BACKUP_DIR

    def tearDown(self):
        config.CONFIG_DIR = self.orig_config_dir
        config.LOG_DIR = self.orig_log_dir
        config.TRAFFIC_BACKUP_DIR = self.orig_traffic_backup
        config.CONFIG_BACKUP_DIR = self.orig_config_backup
        config.LOGS_BACKUP_DIR = self.orig_logs_backup
        config.NODES_BACKUP_DIR = self.orig_nodes_backup

        backups.BACKUP_TYPES["traffic"]["dir"] = config.TRAFFIC_BACKUP_DIR
        backups.BACKUP_TYPES["config"]["dir"] = config.CONFIG_BACKUP_DIR
        backups.BACKUP_TYPES["logs"]["dir"] = config.LOGS_BACKUP_DIR
        backups.BACKUP_TYPES["nodes"]["dir"] = config.NODES_BACKUP_DIR

        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_backups_tier_is_always_on_in_bot(self):
        """Verify modules.backups is ALWAYS_ON so auto-backup background task starts and is not killed."""
        import ast
        bot_path = os.path.join(os.path.dirname(__file__), "..", "bot.py")
        with open(bot_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename="bot.py")

        tier_found = None
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "MODULE_CONFIG":
                        if isinstance(node.value, ast.Dict):
                            for k, v in zip(node.value.keys, node.value.values):
                                if isinstance(k, ast.Constant) and k.value == "modules.backups":
                                    if isinstance(v, ast.Dict):
                                        for subk, subv in zip(v.keys, v.values):
                                            if isinstance(subk, ast.Constant) and subk.value == "tier":
                                                if isinstance(subv, ast.Attribute):
                                                    tier_found = subv.attr
        self.assertEqual(tier_found, "ALWAYS_ON")

    def test_create_config_backup(self):
        """Verify config backup zip creation."""
        dummy_file = os.path.join(config.CONFIG_DIR, "system_config.json")
        with open(dummy_file, "w") as f:
            f.write('{"test": 123}')

        filepath = backups._create_backup_file("config")
        self.assertIsNotNone(filepath)
        self.assertTrue(os.path.exists(filepath))
        self.assertTrue(filepath.endswith(".zip"))

    def test_create_logs_backup(self):
        """Verify logs backup zip creation."""
        dummy_log = os.path.join(config.LOG_DIR, "bot.log")
        with open(dummy_log, "w") as f:
            f.write("test log line")

        filepath = backups._create_backup_file("logs")
        self.assertIsNotNone(filepath)
        self.assertTrue(os.path.exists(filepath))
        self.assertTrue(filepath.endswith(".zip"))

    def test_create_nodes_backup(self):
        """Verify nodes backup zip creation."""
        nodes_db = os.path.join(config.CONFIG_DIR, "nodes.db")
        with open(nodes_db, "wb") as f:
            f.write(b"SQLITE_DUMMY_DATA")

        filepath = backups._create_backup_file("nodes")
        self.assertIsNotNone(filepath)
        self.assertTrue(os.path.exists(filepath))
        self.assertTrue(filepath.endswith(".zip"))

    @patch("modules.traffic.get_current_traffic_total", return_value=(1024, 2048))
    @patch("modules.traffic.save_backup_file")
    def test_create_traffic_backup(self, mock_save, mock_get_total):
        """Verify traffic backup creates a file and saves total traffic."""
        def fake_save(rx, tx):
            ts = int(time.time())
            path = os.path.join(config.TRAFFIC_BACKUP_DIR, f"traffic_backup_{ts}.json")
            with open(path, "w") as f:
                json.dump({"rx": rx, "tx": tx}, f)
        mock_save.side_effect = fake_save

        filepath = backups._create_backup_file("traffic")
        self.assertIsNotNone(filepath)
        self.assertTrue(os.path.exists(filepath))

    def test_rotate_backups(self):
        """Verify backup rotation keeps at most MAX_BACKUPS_PER_TYPE files."""
        for i in range(backups.MAX_BACKUPS_PER_TYPE + 3):
            file_path = os.path.join(config.CONFIG_BACKUP_DIR, f"config_backup_{i}.zip")
            with open(file_path, "w") as f:
                f.write("content")
            # Set staggered mtimes
            os.utime(file_path, (1000 + i, 1000 + i))

        backups._rotate_backups("config")
        remaining = backups._list_backup_files("config")
        self.assertEqual(len(remaining), backups.MAX_BACKUPS_PER_TYPE)

    def test_periodic_backups_task_triggers_all_types(self):
        """Verify periodic_backups_task invokes backups for traffic, config, logs, and nodes."""
        created_types = []

        def fake_create(backup_type):
            created_types.append(backup_type)
            return f"fake_{backup_type}.zip"

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            call_count = 0
            async def fast_sleep(dur):
                nonlocal call_count
                call_count += 1
                if call_count >= 3:
                    raise asyncio.CancelledError()
            mock_sleep.side_effect = fast_sleep

            with patch.object(config, "BACKUP_INTERVAL", 10), \
                 patch.object(backups, "BACKUP_INTERVAL_STEP", 10), \
                 patch.object(backups, "_create_backup_file", side_effect=fake_create):
                try:
                    asyncio.run(backups.periodic_backups_task())
                except asyncio.CancelledError:
                    pass

        self.assertIn("traffic", created_types)
        self.assertIn("config", created_types)
        self.assertIn("logs", created_types)
        self.assertIn("nodes", created_types)


if __name__ == "__main__":
    unittest.main()
