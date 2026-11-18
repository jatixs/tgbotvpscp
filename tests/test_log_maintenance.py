import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from core import log_maintenance as subject


class LogRetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = 2_000_000_000
        self.cutoff = self.now - 7 * 86400

    def file(self, name, mtime=None):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("log", encoding="utf-8")
        os.utime(path, (self.cutoff - 1 if mtime is None else mtime,) * 2)
        return path

    def test_only_known_expired_rotations_are_deleted(self):
        expired = [self.file(name) for name in (
            "bot/bot.log.2026-01-01", "watchdog/watchdog.log.1", "node/node.log.2026-01-01.gz",
        )]
        kept = [self.file(name) for name in (
            "bot/bot.log", "bot/notes.log.backup", "bot/bot.log.2026-01-01.bak",
            "bot/other.log.1", "logs_backups/bot.log.1", "audit/audit.log.1",
            "bot/nested/bot.log.1", "bot/bot.log_2026-01-01",
        )]
        kept.extend([self.file("bot/bot.log.2", self.cutoff), self.file("bot/bot.log.3", self.now)])
        result = subject.cleanup_old_logs(self.root, 7, now=self.now)
        self.assertEqual((result.deleted, result.errors), (3, 0))
        self.assertTrue(all(not path.exists() for path in expired))
        self.assertTrue(all(path.exists() for path in kept))

    def test_missing_directories_and_invalid_retention(self):
        self.assertEqual(subject.cleanup_old_logs(self.root).deleted, 0)
        for days in (0, -1):
            with self.assertRaises(ValueError):
                subject.cleanup_old_logs(self.root, days)

    def test_delete_error_is_reported_and_other_files_are_processed(self):
        blocked = self.file("bot/bot.log.1")
        removed = self.file("watchdog/watchdog.log.1")
        original = os.remove

        def remove(path):
            if Path(path) == blocked:
                raise PermissionError("denied")
            original(path)

        with patch.object(subject.os, "remove", side_effect=remove), self.assertLogs(level="WARNING"):
            result = subject.cleanup_old_logs(self.root, now=self.now)
        self.assertEqual((result.deleted, result.errors), (1, 1))
        self.assertTrue(blocked.exists())
        self.assertFalse(removed.exists())

    def test_symlink_to_log_is_not_removed(self):
        target = self.file("external.txt")
        link = self.root / "bot" / "bot.log.1"
        link.parent.mkdir()
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest("Symlink creation is not permitted")
        result = subject.cleanup_old_logs(self.root, now=self.now)
        self.assertEqual(result.deleted, 0)
        self.assertTrue(link.is_symlink())
        self.assertTrue(target.exists())


class LogTaskTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_periodic_retry_and_cancellation(self):
        results = [subject.CleanupResult(), subject.CleanupResult(errors=1), OSError("disk error")]
        with patch.object(subject, "cleanup_old_logs", side_effect=results) as cleanup, \
                patch.object(subject.asyncio, "sleep", new_callable=AsyncMock) as sleep, \
                self.assertLogs(level="ERROR"):
            sleep.side_effect = [None, None, asyncio.CancelledError()]
            with self.assertRaises(asyncio.CancelledError):
                await subject.maintain_logs("logs", 7)
        self.assertEqual(cleanup.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.await_args_list], [21600, 300, 300])


if __name__ == "__main__":
    unittest.main()
