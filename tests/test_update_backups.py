import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from core import integrity
from core.restart_notification import notify_and_clear_restart_flag

ROOT = Path(__file__).resolve().parents[1]


class UpdateBackupTests(unittest.TestCase):
    def test_integrity_error_does_not_masquerade_as_no_local_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            report = SimpleNamespace(status="ERROR", error_message="missing target revision", modified_files=[])
            with patch.object(integrity, "check_project_integrity", return_value=report):
                with self.assertRaisesRegex(RuntimeError, "missing target revision"):
                    integrity.backup_modified_files(directory)
            self.assertFalse((Path(directory) / ".backups").exists())

    def test_backup_cli_reports_failure_to_installer(self):
        with patch.object(integrity, "backup_modified_files", return_value=(False, "", [])):
            self.assertEqual(integrity.main(["backup"]), 1)


class RestartBackupTests(unittest.IsolatedAsyncioTestCase):
    async def test_restart_notification_preserves_backups_even_when_notification_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            flag = root / "restart_flag.txt"
            saved = []
            for folder in (".backups/pre_update_test", ".backup"):
                path = root / folder / "local.py"
                path.parent.mkdir(parents=True)
                path.write_text("local changes", encoding="utf-8")
                saved.append(path)
            for failure in (None, OSError("offline")):
                flag.write_text("123:456", encoding="utf-8")
                bot = SimpleNamespace(edit_message_text=AsyncMock(side_effect=failure))
                await notify_and_clear_restart_flag(
                    bot, str(flag), lambda _: "en", lambda *_: "restarted", lambda **kwargs: kwargs,
                )
                bot.edit_message_text.assert_awaited_once()
                self.assertFalse(flag.exists())
                for path in saved:
                    self.assertEqual(path.read_text(encoding="utf-8"), "local changes")


if __name__ == "__main__":
    unittest.main()
