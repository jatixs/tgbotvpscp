import asyncio
import importlib.util
import re
import runpy
import secrets
import shutil
import subprocess  # nosec B404
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from node import software_update

ROOT = Path(__file__).resolve().parents[1]
OLD = "a" * 40
NEW = "b" * 40
TEST_GIT = shutil.which("git")


def load_subject(name, path, dependencies):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    subject = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {name: subject, **dependencies}):
        spec.loader.exec_module(subject)
    return subject


class ConfirmationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.subject = load_subject("core.test_node_updates", "core/node_updates.py", {
            "core": SimpleNamespace(config=SimpleNamespace(NODE_OFFLINE_TIMEOUT=20)),
            "core.models": SimpleNamespace(Node=MagicMock(), NodeClientUpdate=MagicMock()),
            "tortoise.transactions": SimpleNamespace(in_transaction=MagicMock()),
        })
        self.subject.eligible_nodes = AsyncMock(return_value=([{"id": 8, "name": "One"}], 2))

    async def test_plan_is_bound_to_owner_branch_and_single_use(self):
        token = (await self.subject.prepare(1, "main"))["token"]
        self.assertIsNone(self.subject.consume(token, 2, "main"))
        self.assertIsNone(self.subject.consume(token, 1, "develop"))
        self.assertEqual(self.subject.consume(token, 1, "main").nodes, (8,))
        self.assertIsNone(self.subject.consume(token, 1, "main"))

    async def test_plan_expires(self):
        with patch.object(self.subject.time, "monotonic", return_value=1):
            token = (await self.subject.prepare(1, "main"))["token"]
        with patch.object(self.subject.time, "monotonic", return_value=1 + self.subject.PLAN_TTL):
            self.assertIsNone(self.subject.consume(token, 1, "main"))

    async def test_no_token_is_issued_without_eligible_nodes(self):
        self.subject.eligible_nodes.return_value = ([], 2)
        plan = await self.subject.prepare(1, "main")
        self.assertEqual(plan, {"nodes": [], "skipped": 2})

    async def test_heartbeat_only_completes_update_on_running_target(self):
        subject = self.subject
        report = {"commit": OLD, "supported": True}
        self.assertEqual(await subject.heartbeat_task(8, report), (None, None))
        subject.NodeClientUpdate.filter.assert_not_called()

        subject.running_commit = NEW
        job = SimpleNamespace(id=20, branch="main", commit=NEW, requested_by=1, expires_at=time.time() + 100)
        query = subject.NodeClientUpdate.filter.return_value
        query.order_by.return_value.first = AsyncMock(return_value=job)
        query.update = AsyncMock(return_value=1)
        task, outcome = await subject.heartbeat_task(8, report)
        self.assertEqual(task, {"id": 20, "branch": "main", "commit": NEW, "expires_at": job.expires_at})
        self.assertIsNone(outcome)
        self.assertEqual(subject.NodeClientUpdate.filter.call_args.kwargs["commit"], NEW)
        query.update.assert_not_awaited()
        self.assertEqual(await subject.heartbeat_task(8, {**report, "commit": NEW}), (None, (1, "updated")))
        query.update.assert_awaited_once_with(status="updated")


class AgentUpdateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.confirmation = secrets.token_urlsafe(16)
        self.node_updates = SimpleNamespace(
            COMMIT=re.compile(r"[0-9a-f]{40}"), BRANCH=re.compile(r"[A-Za-z0-9._/-]{1,255}"),
            agent_update_lock=asyncio.Lock(),
            read_agent_commit=AsyncMock(return_value=OLD),
            queue_updates=AsyncMock(return_value=1),
            prepare=AsyncMock(return_value={
                "token": self.confirmation, "nodes": [{"id": 8, "name": "<Node>"}], "skipped": 0,
            }),
            consume=Mock(),
        )
        self.config = SimpleNamespace(
            ADMIN_USER_ID=1, DEPLOY_MODE="systemd", BASE_DIR=self.directory.name,
            RESTART_FLAG_FILE=str(Path(self.directory.name) / "restart_flag.txt"),
        )
        self.shared = SimpleNamespace(IS_RESTARTING=False, LAST_MESSAGE_IDS={})
        self.integrity = SimpleNamespace(backup_modified_files=Mock(return_value=(True, "", [])))
        self.subject = load_subject("agent_update_subject", "modules/update.py", {
            "aiohttp": MagicMock(), "aiogram": MagicMock(), "aiogram.exceptions": MagicMock(),
            "aiogram.types": MagicMock(), "core.auth": MagicMock(), "core.i18n": MagicMock(),
            "core.messaging": MagicMock(), "core.utils": MagicMock(),
            "core.integrity": self.integrity, "core.config": self.config,
            "core.shared_state": self.shared,
            "core": SimpleNamespace(config=self.config, shared_state=self.shared, node_updates=self.node_updates, utils=MagicMock()),
        })
        self.subject._ = lambda key, lang, **params: key + str(params)
        self.subject.is_allowed = lambda user_id, command: user_id == 1
        self.subject.escape_html = lambda value: value.replace("<", "&lt;").replace(">", "&gt;")
        self.subject.InlineKeyboardButton = SimpleNamespace
        self.subject.InlineKeyboardMarkup = SimpleNamespace
        self.subject.self_terminate = AsyncMock()

    def callback(self, data, user_id=1):
        return SimpleNamespace(
            data=data, from_user=SimpleNamespace(id=user_id), answer=AsyncMock(),
            message=SimpleNamespace(
                chat=SimpleNamespace(id=1), message_id=9, edit_text=AsyncMock(),
            ),
        )

    async def test_telegram_previews_then_requires_valid_confirmation(self):
        self.subject.execute_bot_update = AsyncMock(return_value=1)
        preview = self.callback("do_bot_update:main")
        await self.subject.run_bot_update(preview)
        self.subject.execute_bot_update.assert_not_awaited()
        self.assertIn("&lt;Node&gt;", preview.message.edit_text.call_args.args[0])

        self.node_updates.consume.return_value = None
        await self.subject.run_bot_update(self.callback(f"do_bot_update_nodes:{self.confirmation}"))
        self.subject.execute_bot_update.assert_not_awaited()

        self.node_updates.consume.return_value = SimpleNamespace(branch="main", nodes=(8,))
        await self.subject.run_bot_update(self.callback(f"do_bot_update_nodes:{self.confirmation}", user_id=2))
        self.subject.execute_bot_update.assert_not_awaited()
        await self.subject.run_bot_update(self.callback(f"do_bot_update_agent:{self.confirmation}"))
        self.assertEqual(self.subject.execute_bot_update.call_args.kwargs["node_ids"], ())
        await self.subject.run_bot_update(self.callback(f"do_bot_update_nodes:{self.confirmation}"))
        self.assertEqual(self.subject.execute_bot_update.call_args.kwargs["node_ids"], (8,))

    async def test_failed_agent_dependencies_do_not_queue_nodes(self):
        self.subject.run_command = AsyncMock(side_effect=[
            (0, "", ""), (0, NEW, ""), (0, "", ""), (1, "", "pip failed"), (0, "", ""),
        ])
        with patch.dict(sys.modules, {"core.integrity": self.integrity}):
            with self.assertRaisesRegex(RuntimeError, "Dependency installation failed"):
                await self.subject.execute_bot_update("main", node_ids=(8,))
        self.node_updates.queue_updates.assert_not_awaited()
        self.subject.self_terminate.assert_not_called()
        self.assertFalse(self.shared.IS_RESTARTING)

    async def test_success_queues_the_exact_agent_revision(self):
        self.subject.run_command = AsyncMock(side_effect=[
            (0, "", ""), (0, NEW, ""), (0, "", ""), (0, "", ""), (0, "", ""),
        ])
        with patch.dict(sys.modules, {"core.integrity": self.integrity}):
            self.assertEqual(await self.subject.execute_bot_update("main", node_ids=(8,)), 1)
        self.node_updates.queue_updates.assert_awaited_once_with((8,), "main", NEW, 1)
        self.assertTrue(self.shared.IS_RESTARTING)
        await asyncio.sleep(0)
        self.subject.self_terminate.assert_awaited_once()

    async def test_update_check_uses_checked_out_version_after_restart(self):
        self.subject.utils.get_app_version.return_value = "v1.0.0"
        self.subject.get_current_branch = AsyncMock(return_value="main")
        self.subject.get_remote_version_github = AsyncMock(return_value="v1.1.0")
        self.subject.run_command = AsyncMock(side_effect=[
            (0, "img.shields.io/badge/version-v1.1.0-blue", ""), (0, "", ""),
        ])
        self.assertEqual(await self.subject.get_update_info(), ("v1.1.0", "v1.1.0", "main", False))

    async def test_web_requires_a_confirmed_plan_for_nodes(self):
        def response(payload, status=200):
            return SimpleNamespace(payload=payload, status=status)

        route = lambda _path: lambda handler: handler
        web = SimpleNamespace(
            RouteTableDef=lambda: SimpleNamespace(get=route, post=route),
            json_response=response,
        )
        config = MagicMock(ADMIN_USER_ID=1)
        payload = AsyncMock()
        dependencies = {
            "aiohttp": SimpleNamespace(web=web),
            "core": SimpleNamespace(config=config, node_updates=self.node_updates, nodes_db=MagicMock(), shared_state=self.shared),
            "core.config": config,
            "core.auth": MagicMock(), "core.i18n": MagicMock(),
            "core.shared_state": MagicMock(),
            "core.rbac": SimpleNamespace(is_admin=lambda user: True),
            "core.utils": MagicMock(decrypt_request_payload=payload, encrypted_json_response=response),
            "core.web.auth": SimpleNamespace(get_current_user=lambda request: request.user),
        }
        api = load_subject("core.web.test_update_system", "core/web/api_system.py", dependencies)
        self.subject.execute_bot_update = AsyncMock(return_value=1)
        owner, admin = (SimpleNamespace(user={"id": user_id}) for user_id in (1, 2))
        with patch.dict(sys.modules, {"modules": SimpleNamespace(update=self.subject)}):
            payload.return_value = {"branch": "main", "node_ids": [8]}
            self.assertEqual((await api.api_run_update(owner)).status, 200)
            self.assertEqual(self.subject.execute_bot_update.call_args.kwargs["node_ids"], ())
            self.subject.execute_bot_update.reset_mock()

            payload.return_value["node_confirmation"] = self.confirmation
            self.assertEqual((await api.api_run_update(admin)).status, 403)
            self.node_updates.consume.return_value = None
            self.assertEqual((await api.api_run_update(owner)).status, 409)
            self.subject.execute_bot_update.assert_not_awaited()

            self.node_updates.consume.return_value = SimpleNamespace(nodes=(9,))
            self.assertEqual((await api.api_run_update(owner)).payload["nodes_queued"], 1)
            self.assertEqual(self.subject.execute_bot_update.call_args.kwargs["node_ids"], (9,))


class NodeUpdateCliTests(unittest.TestCase):
    def test_cold_start_loads_config_before_the_event_loop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copyfile(ROOT / "manage.py", root / "manage.py")
            core = root / "core"
            core.mkdir()
            (core / "__init__.py").touch()
            (core / "config.py").write_text(
                "import asyncio\nasyncio.run(asyncio.sleep(0))\n"
                "DEFAULT_LANGUAGE = 'en'\nADMIN_USER_ID = 1\n",
                encoding="utf-8",
            )
            (core / "node_updates.py").write_text(
                "from . import config\n"
                "async def read_agent_commit(): return 'a' * 40\n"
                "async def eligible_nodes(): return [{'id': 8, 'name': 'Node'}], 0\n"
                "async def queue_updates(*args): raise AssertionError('No confirmation given')\n",
                encoding="utf-8",
            )
            (core / "nodes_db.py").write_text("async def init_db(): pass\n", encoding="utf-8")
            (core / "i18n.py").write_text("def _(key, lang, **params): return key\n", encoding="utf-8")
            (root / "tortoise.py").write_text(
                "class Tortoise:\n    @staticmethod\n    async def close_connections(): pass\n",
                encoding="utf-8",
            )

            with patch.dict(sys.modules), patch.object(sys, "path", [str(root), *sys.path]):
                for name in ("core", "core.config", "core.node_updates", "core.nodes_db", "core.i18n", "tortoise"):
                    sys.modules.pop(name, None)
                cli = runpy.run_path(str(root / "manage.py"))
                with patch("builtins.input", return_value="n") as confirm, patch("builtins.print"):
                    self.assertEqual(cli["main"](["update-nodes"]), 0)

        confirm.assert_called_once_with("node_client_update_cli_prompt")


@unittest.skipUnless(TEST_GIT, "Git is required to exercise the node checkout")
class NodeCheckoutTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.origin = root / "origin"
        self.origin.mkdir()
        self.checkout = root / "client"
        self.git(self.origin, "init", "-b", "main")
        self.git(self.origin, "config", "user.name", "Node update test")
        self.git(self.origin, "config", "user.email", "node-update@example.invalid")
        (self.origin / "node").mkdir()
        for name in ("node/node.py", "node/endpoint_migration.py", "node/software_update.py", "network_validation.py"):
            (self.origin / name).write_text("value = 1\n")
        (self.origin / ".gitignore").write_text(".env\n/config/\n")
        (self.origin / "excluded.py").write_text("value = 1\n")
        self.commit("initial")
        self.git(root, "clone", "--depth=1", self.origin.as_uri(), str(self.checkout))
        self.git(self.checkout, "sparse-checkout", "set", "--no-cone", "/node/", "/network_validation.py", "/.gitignore")
        (self.checkout / ".env").write_text("MODE=node\n")
        (self.checkout / "config").mkdir()
        (self.checkout / "config" / "state").write_text("state")

    @staticmethod
    def git(path, *args):
        # The executable is resolved on the test host. Arguments come from the temporary repo fixture.
        return subprocess.check_output(  # nosec B603, B607
            ["git", "-C", str(path), *args], executable=TEST_GIT, shell=False,
            stderr=subprocess.PIPE, text=True,
        ).strip()

    def commit(self, message):
        self.git(self.origin, "add", ".")
        self.git(self.origin, "commit", "--no-gpg-sign", "-m", message)
        return self.git(self.origin, "rev-parse", "HEAD")

    def updater(self, *, fail_restart=False):
        real_run = subprocess.run
        self.restarts = 0

        def run(argv, *args, **kwargs):
            if argv[0] == "/usr/bin/systemctl":
                self.assertFalse(kwargs["shell"])
                self.assertEqual(argv[-1], software_update.SERVICE)
                if argv[1] == "show":
                    return SimpleNamespace(stdout=str(software_update.os.getpid()).encode())
                self.assertEqual(argv[1:-1], ["--no-block", "restart"])
                self.restarts += 1
                if fail_restart:
                    raise subprocess.CalledProcessError(1, argv)
                return SimpleNamespace(stdout=b"")
            if argv[0] == "/usr/bin/git":
                self.assertFalse(kwargs["shell"])
                argv = [TEST_GIT, *argv[1:]]
            return real_run(argv, *args, **kwargs)

        patcher = patch.object(software_update.subprocess, "run", side_effect=run)
        patcher.start()
        self.addCleanup(patcher.stop)
        with patch.object(software_update.os, "geteuid", return_value=0, create=True):
            return software_update.ClientUpdater(str(self.checkout))

    def update(self, updater, commit):
        with patch.object(software_update, "REPOSITORY", self.origin.as_uri()):
            updater.offer({"id": 1, "branch": "main", "commit": commit, "expires_at": time.time() + 100})
            updater.worker.join(15)
            self.assertFalse(updater.worker.is_alive())

    def test_updates_to_pinned_commit_and_preserves_node_files(self):
        (self.origin / "node" / "node.py").write_text("value = 2\n")
        approved = self.commit("approved")
        (self.origin / "node" / "node.py").write_text("value = 3\n")
        self.commit("unapproved newer tip")
        updater = self.updater()
        self.update(updater, approved)
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), approved)
        self.assertEqual((self.checkout / ".env").read_text(), "MODE=node\n")
        self.assertEqual((self.checkout / "config" / "state").read_text(), "state")
        self.assertFalse((self.checkout / "excluded.py").exists())
        self.assertEqual(self.restarts, 1)
        self.assertTrue(updater.report()["busy"])

    def test_failed_restart_restores_previous_commit(self):
        updater = self.updater(fail_restart=True)
        (self.origin / "node" / "node.py").write_text("value = 2\n")
        approved = self.commit("approved")
        with self.assertLogs(level="ERROR"):
            self.update(updater, approved)
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), updater.commit)
        self.assertEqual(updater.report()["failed"], 1)
        self.assertFalse(updater.report()["busy"])

    def test_rejects_revision_outside_approved_branch(self):
        updater = self.updater()
        self.git(self.origin, "checkout", "-b", "other")
        (self.origin / "node" / "node.py").write_text("value = 2\n")
        other = self.commit("another branch")
        with self.assertLogs(level="ERROR"):
            self.update(updater, other)
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), updater.commit)
        self.assertEqual(self.restarts, 0)


if __name__ == "__main__":
    unittest.main()
