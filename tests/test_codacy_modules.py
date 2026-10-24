import ast
import asyncio
import importlib.util
import json
import re
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, mock_open, patch


ROOT = Path(__file__).resolve().parents[1]


def load_functions(filename, names, **dependencies):
    """Load backend functions without requiring the optional Telegram runtime."""
    imports = {
        name: MagicMock()
        for name in (
            "aiohttp", "yaml", "psutil", "aiogram", "aiogram.types",
            "aiogram.exceptions", "core", "core.auth", "core.config",
            "core.i18n", "core.keyboards", "core.messaging", "core.rbac",
            "core.shared_state", "core.utils", "node", "node.input_validation",
        )
    }
    imports["core"].config.CONFIG_DIR = "config"
    spec = importlib.util.spec_from_file_location(
        f"codacy_modules_{Path(filename).stem}", ROOT / "modules" / filename,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load module {filename}")
    subject = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, imports):
        spec.loader.exec_module(subject)
    for name, value in dependencies.items():
        setattr(subject, name, value)
    for name in names:
        if not callable(getattr(subject, name)):
            raise TypeError(f"Expected a function: {name}")
    return subject


class ModuleFallbackTests(unittest.TestCase):
    def test_changed_modules_have_no_silent_broad_exception_handlers(self):
        filenames = (
            "backups.py", "client_alerts.py", "nodes.py", "notifications.py",
            "optimize.py", "selftest.py", "services.py", "speedtest.py", "traffic.py",
        )
        for filename in filenames:
            source = ast.parse((ROOT / "modules" / filename).read_text(encoding="utf-8"))
            for node in ast.walk(source):
                if not isinstance(node, ast.ExceptHandler):
                    continue
                if not isinstance(node.type, ast.Name) or node.type.id != "Exception":
                    continue
                with self.subTest(filename=filename, line=node.lineno):
                    self.assertFalse(
                        len(node.body) == 1 and isinstance(node.body[0], (ast.Pass, ast.Continue)),
                    )

    def test_speedtest_detection_survives_unreadable_config_and_missing_binary(self):
        for installed, expected in (("iperf3", "IPERF3"), (None, "AUTO")):
            with self.subTest(installed=installed):
                runner = Mock(side_effect=FileNotFoundError("speedtest"))
                subject = load_functions(
                    "speedtest.py", ["get_speedtest_mode"],
                    _SPEEDTEST_MODE_CACHE=None,
                    SPEEDTEST_MODE_FILE="mode",
                    os=SimpleNamespace(path=SimpleNamespace(exists=lambda path: True)),
                    subprocess=SimpleNamespace(
                        run=runner, SubprocessError=subprocess.SubprocessError,
                    ),
                    shutil=SimpleNamespace(which=lambda name: installed),
                )
                with patch("builtins.open", side_effect=PermissionError("mode")), self.assertLogs(level="DEBUG"):
                    self.assertEqual(subject.get_speedtest_mode(), expected)
                runner.assert_called_once_with(
                    ["speedtest", "--version"], capture_output=True, timeout=5,
                )

    def test_speedtest_config_keeps_priority_over_binary_detection(self):
        runner = Mock()
        subject = load_functions(
            "speedtest.py", ["get_speedtest_mode"],
            _SPEEDTEST_MODE_CACHE=None,
            SPEEDTEST_MODE_FILE="mode",
            os=SimpleNamespace(path=SimpleNamespace(exists=lambda path: True)),
            subprocess=SimpleNamespace(run=runner),
        )
        with patch("builtins.open", mock_open(read_data="ru\n")):
            self.assertEqual(subject.get_speedtest_mode(), "IPERF3")
        runner.assert_not_called()

    def test_services_pass_validated_names_as_single_arguments(self):
        runner = Mock(return_value=SimpleNamespace(
            returncode=0, stdout="LoadState=loaded\nActiveState=active\nSubState=running\n",
            stderr="",
        ))
        subject = load_functions(
            "services.py", ["_validate_name", "get_systemd_status"],
            _VALID_NAME_RE=re.compile(r"^[a-zA-Z0-9._@/:-]+$"),
            subprocess=SimpleNamespace(run=runner, PIPE=subprocess.PIPE),
        )
        self.assertEqual(subject.get_systemd_status("nginx.service"), "running")
        self.assertEqual(runner.call_args.args[0][-2:], ["--", "nginx.service"])
        self.assertNotIn("shell", runner.call_args.kwargs)
        runner.reset_mock()
        with self.assertLogs(level="ERROR"):
            self.assertEqual(subject.get_systemd_status("nginx; touch marker"), "error")
        runner.assert_not_called()


class ModuleAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_ping_uses_only_pinned_public_targets(self):
        for resolved in (None, "8.8.8.8"):
            with self.subTest(resolved=resolved):
                proc = SimpleNamespace(communicate=AsyncMock(return_value=(
                    b"rtt min/avg/max/mdev = 1.0/2.0/3.0/0.0 ms", b"",
                )))
                spawn = AsyncMock(return_value=proc)
                resolver = Mock(return_value=resolved)
                subject = load_functions(
                    "speedtest.py", ["get_ping_async"],
                    asyncio=SimpleNamespace(
                        create_subprocess_exec=spawn, to_thread=asyncio.to_thread,
                        subprocess=asyncio.subprocess,
                    ),
                    resolve_public_host=resolver,
                    platform=SimpleNamespace(system=lambda: "Linux"),
                    PING_COUNT=3, PING_TIMEOUT_SEC=2, re=re,
                )
                result = await subject.get_ping_async("-malicious-host")
                resolver.assert_called_once_with("-malicious-host")
                if resolved is None:
                    self.assertIsNone(result)
                    spawn.assert_not_awaited()
                else:
                    self.assertEqual(result, 2.0)
                    self.assertEqual(spawn.call_args.args[-1], "8.8.8.8")

    async def test_iperf_rejects_invalid_or_private_feed_targets(self):
        for valid, resolved in ((False, None), (True, None)):
            with self.subTest(valid=valid):
                spawn = AsyncMock()
                subject = load_functions(
                    "speedtest.py", ["run_iperf_test_async"],
                    Bot=object,
                    asyncio=SimpleNamespace(
                        create_subprocess_exec=spawn, to_thread=asyncio.to_thread,
                    ),
                    is_valid_iperf_server=lambda server: valid,
                    resolve_public_host=lambda host: resolved,
                )
                result = await subject.run_iperf_test_async(
                    None, 1, 1, {"host": "127.0.0.1", "port": 5201}, 1.0, "en",
                )
                self.assertIn("server", result)
                spawn.assert_not_awaited()

    async def test_ssh_log_path_is_a_single_argument_and_invalid_offset_is_logged(self):
        log_path = "/host/log path/auth.log; touch marker"
        proc = SimpleNamespace(
            communicate=AsyncMock(return_value=(b"Accepted password for root from 192.0.2.1\n", b"")),
        )
        spawn = AsyncMock(return_value=proc)
        subject = load_functions(
            "selftest.py", ["get_last_ssh_login"],
            asyncio=SimpleNamespace(
                create_subprocess_exec=spawn, subprocess=asyncio.subprocess,
            ),
            os=SimpleNamespace(
                path=SimpleNamespace(exists=lambda path: True, basename=lambda path: "auth.log"),
            ),
            get_host_path=lambda path: log_path,
            get_ip_data_full=AsyncMock(return_value=("flag", "invalid")),
            escape_html=lambda value: value,
            get_server_timezone_label=lambda: "UTC",
            datetime=datetime, timedelta=timedelta, timezone=timezone, re=re,
            _=lambda key, lang, **values: values,
        )
        with self.assertLogs(level="DEBUG"):
            result = await subject.get_last_ssh_login("en")
        self.assertEqual(result["user"], "root")
        self.assertEqual(spawn.call_args.args, ("tail", "-n", "200", "--", log_path))

    async def test_notification_monitors_use_argv_without_a_shell(self):
        class EmptyStream:
            def __aiter__(self):
                return self

            async def __anext__(self):
                raise StopAsyncIteration

        for function_name, args, expected in (
            (
                "reliable_journal_monitor",
                (),
                ("journalctl", "-n", "0", "-f", "-o", "cat", "_COMM=sshd"),
            ),
            (
                "reliable_tail_log_monitor",
                ("/host/log path/auth.log; touch marker",),
                ("tail", "-n", "0", "-f", "--", "/host/log path/auth.log; touch marker"),
            ),
        ):
            with self.subTest(monitor=function_name):
                spawn = AsyncMock(return_value=SimpleNamespace(stdout=EmptyStream()))
                subject = load_functions(
                    "notifications.py", [function_name],
                    asyncio=SimpleNamespace(
                        create_subprocess_exec=spawn,
                        subprocess=asyncio.subprocess,
                        sleep=AsyncMock(side_effect=asyncio.CancelledError),
                        CancelledError=asyncio.CancelledError,
                    ),
                    os=SimpleNamespace(path=SimpleNamespace(exists=lambda path: True)),
                )
                with self.assertRaises(asyncio.CancelledError):
                    await getattr(subject, function_name)(None, *args, "logins", AsyncMock())
                self.assertEqual(spawn.call_args.args, expected)
                self.assertTrue(spawn.call_args.kwargs["start_new_session"])

    async def test_invalid_cached_speedtest_port_does_not_hide_valid_servers(self):
        response = SimpleNamespace(status=500)
        request = AsyncMock()
        request.__aenter__.return_value = response
        session = SimpleNamespace(get=Mock(return_value=request))
        session_context = AsyncMock()
        session_context.__aenter__.return_value = session
        subject = load_functions(
            "speedtest.py", ["fetch_servers_async"],
            Any=object,
            aiohttp=SimpleNamespace(ClientSession=lambda: session_context),
            os=SimpleNamespace(path=SimpleNamespace(exists=lambda path: True)),
            json=json, SERVER_LIST_URL="https://example.test",
            LOCAL_CACHE_FILE="cache.json",
        )
        servers = [
            {"IP/HOST": "invalid.example", "PORT": "not-a-port"},
            {"IP/HOST": "valid.example", "PORT": "5201-5209"},
        ]
        with patch("builtins.open", mock_open(read_data=json.dumps(servers))), self.assertLogs(level="DEBUG"):
            result = await subject.fetch_servers_async(None)
        self.assertEqual([(server["host"], server["port"]) for server in result], [
            ("valid.example", 5201),
        ])


if __name__ == "__main__":
    unittest.main()
