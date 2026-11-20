"""Regression checks for tgcp-bot command dispatch and DB bootstrap timing.

No production databases, services, or node operations are touched by these tests.
"""
import sys
import types
import unittest
from unittest.mock import patch

import manage


class TrackingCore(types.ModuleType):
    def __init__(self):
        super().__init__("core")
        self.config_seen = False
        self.config = object()

    def __getattribute__(self, key):
        if key == "config":
            object.__setattr__(self, "config_seen", True)
        return super().__getattribute__(key)


class CommandDispatchTests(unittest.TestCase):
    DB_COMMANDS = [
        ["adduser", "--id", "12345", "--name", "Tester"],
        ["webpass"],
        ["stats"],
        ["update-nodes", "--branch", "hotfix/1.28.1"],
        ["tls", "status"],
        ["tls", "check"],
        ["tls", "finalize"],
    ]
    NO_DB_COMMANDS = [["cleanlogs"], ["restart"], ["status"]]

    def run_mocked_command(self, argv, expects_config):
        core = TrackingCore()
        calls = []

        async def fake_command(*args):
            calls.append(("command", argv[0]))

        def fake_run(coroutine):
            try:
                calls.append(("run", core.config_seen))
                self.assertEqual(
                    core.config_seen, expects_config,
                    f"{argv} imported DB config at the wrong stage",
                )
            finally:
                coroutine.close()

        names = [
            "cmd_adduser", "cmd_webpass", "cmd_stats", "cmd_update_nodes",
            "cmd_tls_status", "cmd_tls_check", "cmd_tls_finalize",
            "cmd_cleanlogs", "cmd_restart", "cmd_status",
        ]
        patches = [patch.object(manage, n, fake_command) for n in names]
        patches += [
            patch.object(manage.asyncio, "run", fake_run),
            patch.dict(sys.modules, {"core": core}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        result = manage.main(argv)
        self.assertEqual(result, 0, f"Command {argv} failed")
        self.assertEqual(len([c for c in calls if c[0] == "run"]), 1)
        # Stop mocks before the next command in the same test.
        for p in reversed(patches):
            p.stop()

    def test_db_commands_import_config_before_event_loop(self):
        for command in self.DB_COMMANDS:
            with self.subTest(command=command):
                self.run_mocked_command(command, True)

    def test_service_and_log_commands_do_not_require_config_bootstrap(self):
        for command in self.NO_DB_COMMANDS:
            with self.subTest(command=command):
                self.run_mocked_command(command, False)

    def test_integrity_runs_synchronously(self):
        core = TrackingCore()
        with patch.dict(sys.modules, {"core": core}), \
             patch.object(manage, "cmd_integrity", return_value=0) as action, \
             patch.object(manage.asyncio, "run", side_effect=AssertionError("Unexpected loop")):
            self.assertEqual(manage.main(["integrity", "check"]), 0)
            action.assert_called_once()
            self.assertFalse(core.config_seen)


if __name__ == "__main__":
    unittest.main()
