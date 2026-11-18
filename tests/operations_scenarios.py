"""Isolated integration cases: no real server configuration or commands are loaded."""
import asyncio
import importlib.util
import json
import sys
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cryptography.fernet import Fernet
from tortoise import Tortoise

sys.modules["core.config"] = SimpleNamespace(CIPHER_SUITE=Fernet(Fernet.generate_key()))

from core import operations
from core.models import Node, NodeOperation
from node.operation_journal import OperationJournal, heartbeat_state, open_journal

# Test-only encrypted envelope. The production wire cipher is not implemented here:
# these API tests exercise authorization, secrecy and response structure.
TEST_WEB_CIPHER = Fernet(Fernet.generate_key())


def encrypt_web_fixture(value):
    if not value:
        return ""
    return TEST_WEB_CIPHER.encrypt(str(value).encode("utf-8")).decode("ascii")


def decrypt_web_fixture(value):
    return TEST_WEB_CIPHER.decrypt(value.encode("ascii")).decode("utf-8")


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_url = "sqlite://" + str(Path(self.temp.name) / "master.db")
        await Tortoise.init(db_url=self.db_url, modules={"models": ["core.models"]})
        await Tortoise.generate_schemas()
        self.node = await Node.create(token_hash="one", token_safe="secret", name="One", ip="127.0.0.1")
        self.journal = OperationJournal(Path(self.temp.name) / "node.db")

    async def asyncTearDown(self):
        await Tortoise.close_connections()
        self.temp.cleanup()

    async def enqueue(self, command="uptime"):
        return await operations.enqueue("one", {"command": command, "user_id": 42})

    async def heartbeat(self, reports=None, reliable=True, busy=False):
        return await operations.exchange(self.node.id, reports or [], reliable=reliable, busy=busy)

    async def test_lost_response_resends_same_id_and_executes_once(self):
        op = await self.enqueue()
        first, _, _ = await self.heartbeat()
        resent, _, _ = await self.heartbeat()
        self.assertEqual(first, resent)
        command = Mock(side_effect=lambda task: self.journal.finish(task["operation_id"], "done"))
        self.journal.execute(first[0], command)
        self.journal.execute(resent[0], command)
        command.assert_called_once()
        tasks, notices, ack = await self.heartbeat(self.journal.reports())
        self.assertEqual(tasks, [])
        self.assertEqual(notices, [{"user_id": 42, "command": "uptime", "result": "done"}])
        # Losing the acknowledgement does not duplicate notifications or erase the result.
        self.assertEqual(await self.heartbeat(self.journal.reports()), ([], [], ack))
        self.journal.acknowledge(ack)
        self.assertEqual(self.journal.reports(), [])
        self.journal.execute(first[0], command)
        command.assert_called_once()
        saved = await NodeOperation.get(id=op.id)
        self.assertEqual(saved.status, "finished")
        self.assertEqual(json.loads(saved.result), "done")

    async def test_concurrent_enqueue_does_not_overwrite_commands(self):
        await asyncio.gather(*(self.enqueue(str(i)) for i in range(40)))
        self.assertEqual(await NodeOperation.all().count(), 40)
        tasks, _, _ = await self.heartbeat()
        self.assertEqual(len(tasks), 20)
        for task in tasks:
            self.journal.claim(task["operation_id"])
        next_tasks, _, _ = await self.heartbeat(self.journal.reports())
        self.assertEqual(len(next_tasks), 20)
        self.assertTrue(set(t["operation_id"] for t in tasks).isdisjoint(t["operation_id"] for t in next_tasks))

    async def test_legacy_queue_migrates_once_and_retains_old_task_shape(self):
        old_task = {"command": "reboot", "user_id": 42}
        self.node.tasks = [old_task]
        await self.node.save(update_fields=["tasks"])
        self.assertEqual((await self.heartbeat(reliable=False))[0], [old_task])
        self.assertEqual((await self.heartbeat(reliable=False))[0], [])
        self.assertEqual(await NodeOperation.all().count(), 1)
        self.assertEqual((await NodeOperation.first()).status, "legacy_sent")
        self.assertEqual((await Node.get(id=self.node.id)).tasks, [])

    async def test_schema_upgrade_keeps_existing_node_and_queued_task(self):
        # This is a disposable database created in asyncSetUp, never the application database.
        await Tortoise.get_connection("default").execute_script("DROP TABLE node_operations")
        self.node.tasks = [{"command": "uptime", "user_id": 42}]
        await self.node.save(update_fields=["tasks"])
        await Tortoise.generate_schemas()
        tasks, _, _ = await self.heartbeat()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["command"], "uptime")
        self.assertEqual((await Node.get(id=self.node.id)).token_safe, "secret")

    async def test_concurrent_legacy_heartbeats_deliver_only_once(self):
        await self.enqueue("reboot")
        first, second = await asyncio.gather(self.heartbeat(reliable=False), self.heartbeat(reliable=False))
        self.assertEqual(len(first[0]) + len(second[0]), 1)

    async def test_downgrade_never_repeats_dispatched_commands(self):
        await self.enqueue("reboot")
        await self.heartbeat()
        await self.enqueue("uptime")
        tasks, _, _ = await self.heartbeat(reliable=False)
        self.assertEqual([t["command"] for t in tasks], ["uptime"])

    async def test_busy_client_acknowledges_results_without_receiving_commands(self):
        await self.enqueue()
        task = (await self.heartbeat())[0][0]
        self.journal.execute(task, Mock())
        await self.enqueue()
        tasks, _, ack = await self.heartbeat(self.journal.reports(), busy=True)
        self.assertEqual(tasks, [])
        self.assertEqual(ack, [task["operation_id"]])

    async def test_report_cannot_change_another_nodes_operation(self):
        op = await self.enqueue()
        other = await Node.create(token_hash="two", token_safe="secret", name="Two", ip="127.0.0.2")
        result = await operations.exchange(other.id, [{"id": op.delivery_id.hex, "status": "finished"}], reliable=True, busy=True)
        self.assertEqual(result, ([], [], []))
        self.assertEqual((await NodeOperation.get(id=op.id)).status, "queued")

    async def test_interrupted_execution_becomes_unknown_without_retry(self):
        op = await self.enqueue()
        task = (await self.heartbeat())[0][0]
        self.journal.claim(task["operation_id"])
        journal = OperationJournal(self.journal.path)
        command = Mock()
        journal.execute(task, command)
        command.assert_not_called()
        await self.heartbeat(journal.reports())
        self.assertEqual((await NodeOperation.get(id=op.id)).status, "unknown")

    async def test_database_reopen_preserves_queue_and_history(self):
        op = await self.enqueue()
        await Tortoise.close_connections()
        await Tortoise.init(db_url=self.db_url, modules={"models": ["core.models"]})
        await Tortoise.generate_schemas()
        self.assertEqual((await self.heartbeat())[0][0]["operation_id"], op.delivery_id.hex)

    async def test_history_pagination_and_filters(self):
        await asyncio.gather(*(self.enqueue() for _ in range(53)))
        rows, before = await operations.history(node_id=self.node.id, status="queued")
        self.assertEqual(len(rows), 50)
        older, end = await operations.history(before=before)
        self.assertEqual(len(older), 3)
        self.assertIsNone(end)
        self.assertTrue({r.id for r in rows}.isdisjoint(r.id for r in older))
        self.assertEqual(await operations.history(status="failed"), ([], None))

    async def test_payload_and_result_encrypted_at_rest(self):
        op = await self.enqueue()
        op.result = json.dumps("private output")
        await op.save()
        raw = await Tortoise.get_connection("default").execute_query_dict("SELECT payload,result FROM node_operations")
        self.assertNotIn("uptime", raw[0]["payload"])
        self.assertNotIn("private output", raw[0]["result"])

    async def test_invalid_reports_are_ignored(self):
        for report in (None, 1, {"id": "bad", "status": "finished"}, {"id": uuid.uuid4().hex, "status": []}):
            self.assertEqual(await self.heartbeat([report]), ([], [], []))

    async def test_traffic_samples_reuse_one_card_with_new_delivery_ids(self):
        task = {"command": "traffic", "user_id": 42, "traffic_session": uuid.uuid4().hex}
        operation = await operations.enqueue("one", task)
        created_at = operation.created_at
        first = (await self.heartbeat())[0][0]
        self.journal.execute(first, lambda job: self.journal.finish(job["operation_id"], "sample one"))
        _, notices, lost_ack = await self.heartbeat(self.journal.reports())
        self.assertEqual(notices[0]["traffic_session"], task["traffic_session"])
        operation = await operations.enqueue("one", task, traffic_operation_id=operation.id)
        self.assertNotEqual(operation.delivery_id.hex, first["operation_id"])
        self.assertEqual(operation.created_at, created_at)
        self.assertEqual(json.loads(operation.result), "sample one")
        second, notices, ack = await self.heartbeat(self.journal.reports())
        self.assertEqual(ack, lost_ack)
        self.assertEqual(notices, [])  # A repeated old receipt must not replace the new sample.
        self.journal.acknowledge(ack)
        self.journal.claim(second[0]["operation_id"])
        await self.heartbeat(self.journal.reports())
        self.assertEqual(json.loads((await NodeOperation.get(id=operation.id)).result), "sample one")
        self.journal.finish(second[0]["operation_id"], "sample two")
        await self.heartbeat(self.journal.reports())
        self.assertEqual(json.loads((await NodeOperation.get(id=operation.id)).result), "sample two")
        self.assertEqual(await NodeOperation.all().count(), 1)

    async def test_traffic_polling_does_not_accumulate_offline_or_inflight_tasks(self):
        task = {"command": "traffic", "user_id": 42, "traffic_session": uuid.uuid4().hex}
        operation = await operations.enqueue("one", task)
        for status in ("queued", "dispatched", "running"):
            operation.status = status
            await operation.save()
            await asyncio.gather(*(operations.enqueue("one", task, traffic_operation_id=operation.id) for _ in range(5)))
            saved = await NodeOperation.get(id=operation.id)
            self.assertEqual(saved.delivery_id, operation.delivery_id)
            self.assertEqual(saved.status, status)
        self.assertEqual(await NodeOperation.all().count(), 1)

    async def test_concurrent_traffic_refresh_rotates_delivery_id_only_once(self):
        task = {"command": "traffic", "user_id": 42, "traffic_session": uuid.uuid4().hex}
        operation = await operations.enqueue("one", task)
        operation.status = "finished"
        await operation.save()
        refreshed = await asyncio.gather(*(operations.enqueue("one", task, traffic_operation_id=operation.id) for _ in range(5)))
        self.assertEqual(len({row.delivery_id for row in refreshed}), 1)
        self.assertNotEqual(refreshed[0].delivery_id, operation.delivery_id)

    async def test_sessions_users_and_one_shot_commands_stay_separate(self):
        task = {"command": "traffic", "user_id": 42, "traffic_session": uuid.uuid4().hex}
        operation = await operations.enqueue("one", task)
        for changed in ({"traffic_session": uuid.uuid4().hex}, {"user_id": 43}, {"command": "reboot"}):
            with self.assertRaises(ValueError):
                await operations.enqueue("one", {**task, **changed}, traffic_operation_id=operation.id)
        second = await operations.enqueue("one", {**task, "traffic_session": uuid.uuid4().hex})
        self.assertNotEqual(second.id, operation.id)
        self.assertNotEqual((await self.enqueue()).id, (await self.enqueue()).id)

    async def test_legacy_traffic_client_uses_same_card_and_original_payload(self):
        task = {"command": "traffic", "user_id": 42, "traffic_session": uuid.uuid4().hex}
        operation = await operations.enqueue("one", task)
        first = (await self.heartbeat(reliable=False))[0]
        await operations.enqueue("one", task, traffic_operation_id=operation.id)
        second = (await self.heartbeat(reliable=False))[0]
        self.assertEqual(first, second)
        self.assertNotIn("operation_id", second[0])
        self.assertEqual(await NodeOperation.all().count(), 1)


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.journal = OperationJournal(Path(self.temp.name) / "node.db")
        self.id = uuid.uuid4().hex

    def test_concurrent_claim_has_one_winner(self):
        with ThreadPoolExecutor(max_workers=8) as executor:
            outcomes = list(executor.map(self.journal.claim, [self.id] * 16))
        self.assertEqual(sum(outcomes), 1)

    def test_failure_is_persistent_and_not_retried(self):
        command = Mock(side_effect=RuntimeError("offline"))
        task = {"operation_id": self.id}
        with self.assertRaises(RuntimeError):
            self.journal.execute(task, command)
        self.journal.execute(task, command)
        command.assert_called_once()
        self.assertEqual(self.journal.reports()[0]["status"], "failed")

    def test_legacy_command_keeps_existing_execution_path(self):
        command = Mock()
        self.journal.execute({"command": "uptime"}, command)
        command.assert_called_once_with({"command": "uptime"})
        self.assertEqual(self.journal.reports(), [])

    def test_ack_cannot_remove_running_command(self):
        self.journal.claim(self.id)
        self.journal.acknowledge([self.id])
        self.assertEqual(self.journal.reports()[0]["status"], "running")
        self.journal.acknowledge(None)

    def test_unavailable_journal_pauses_commands_without_stopping_heartbeat(self):
        with self.assertLogs(level="ERROR"):
            journal = open_journal(Path(self.temp.name) / "missing" / "node.db")
        self.assertIsNone(journal)
        self.assertEqual(heartbeat_state(journal), ([], True))
        with patch.object(self.journal, "reports", side_effect=OSError("disk unavailable")), self.assertLogs(level="ERROR"):
            self.assertEqual(heartbeat_state(self.journal), ([], True))
        self.assertEqual(heartbeat_state(self.journal), ([], False))


class HistoryRenderingTests(unittest.TestCase):
    def test_service_action_names_target_without_exposing_other_parameters(self):
        sensitive_token = uuid.uuid4().hex
        with patch.dict(sys.modules, {"core.i18n": Mock(), "core.utils": Mock()}):
            from core.web.operation_history import present
        row = SimpleNamespace(
            id=1, node_id=2, command="service_action", status="queued", requested_by=42,
            result=None, created_at=1, updated_at=1,
            payload=json.dumps({"action": "restart", "service": "nginx", "token": sensitive_token}),
        )
        view = present(row, {2: "Server"}, "en")
        self.assertEqual(view["command"], "Restart: nginx")
        self.assertNotIn(sensitive_token, json.dumps(view))

    def test_filters_reject_invalid_values(self):
        for query in ({"node_id": "abc"}, {"node_id": "-1"}, {"status": "<script>"}, {"before": "-1"}):
            with self.assertRaises(ValueError):
                operations.parse_filters(query)

    def test_template_escapes_server_names_and_results_in_both_languages(self):
        from jinja2 import Environment, FileSystemLoader, select_autoescape
        with patch.dict(sys.modules, {"core.i18n": Mock(), "core.utils": Mock()}):
            from core.web.operation_history import LABELS
        env = Environment(loader=FileSystemLoader(Path(__file__).resolve().parents[1] / "core/templates"), autoescape=select_autoescape())
        malicious = '<script>alert("private")</script>'
        for lang in ("ru", "en"):
            rendered = env.get_template("operations.html").render(
                lang=lang, labels=LABELS[lang], filters={"node_id": 0, "status": "", "before": 0},
                nodes={1: malicious}, statuses=["queued"], next_before=None,
                rows=[{"node_id": 1, "node_name": malicious, "result": malicious, "status": "finished"}],
            )
            self.assertNotIn(malicious, rendered)
            self.assertIn("&lt;script&gt;", rendered)
            self.assertIn(LABELS[lang]["title"], rendered)


class HistoryAccessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
        root = Path(__file__).resolve().parents[1]
        auth = Mock()
        self.auth = auth
        auth.get_current_user.side_effect = lambda request: {
            "owner": {"id": 1, "role": "users"}, "admin": {"id": 2, "role": "admins"},
            "reader": {"id": 3, "role": "users"},
        }.get(request.headers.get("X-Test-User"))
        config = SimpleNamespace(
            BASE_DIR=str(root), ADMIN_USER_ID=1, DEFAULT_LANGUAGE="en", TG_BOT_NAME="Test",
            NODE_OFFLINE_TIMEOUT=20,
        )
        utils = MagicMock()
        utils.get_app_version.return_value = "vtest"
        utils.get_web_key.return_value = "fixture-only-web-key"
        utils.encrypt_for_web.side_effect = encrypt_web_fixture
        utils.encrypted_json_response.side_effect = lambda data, status=200: web.json_response(
            {"d": encrypt_web_fixture(json.dumps(data))}, status=status,
        )
        i18n = Mock()
        i18n.get_user_lang.return_value = "en"
        i18n.get_text.side_effect = lambda key, lang, **kwargs: key
        deps = {
            "core.config": config, "core.utils": utils, "core.i18n": i18n,
            "core.shared_state": SimpleNamespace(ALLOWED_USERS={}), "core.keyboards": Mock(),
            "core.web.auth": auth, "core.web.avatar": Mock(), "core.nodes_db": Mock(),
            "core.node_updates": Mock(), "core.messaging": Mock(), "modules.services": Mock(),
        }
        self.modules = patch.dict(sys.modules, deps)
        self.modules.start()
        self.addCleanup(self.modules.stop)
        asset_spec = importlib.util.spec_from_file_location("core.web.test_private_assets", root / "core/web/private_assets.py")
        assets = importlib.util.module_from_spec(asset_spec)
        asset_spec.loader.exec_module(assets)
        app = web.Application(middlewares=[assets.protect_private_assets])
        assets.register_private_assets(app)
        app.router.add_static("/static", str(root / "core/static"))
        self.shutdown = asyncio.Event()
        app["shutdown_event"] = self.shutdown

        async def on_shutdown(app):
            self.shutdown.set()

        app.on_shutdown.append(on_shutdown)
        for name in ("views", "api_nodes"):
            spec = importlib.util.spec_from_file_location(f"core.web.test_{name}", root / "core/web" / f"{name}.py")
            subject = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(subject)
            handler = subject.handle_operations_page if name == "views" else subject.list_operations
            app.router.add_get("/operations" if name == "views" else "/api/operations", handler)
            if name == "api_nodes":
                self.api = subject
                app.router.add_get("/api/operations/stream", subject.stream_operations)
                app.router.add_get("/api/services", subject.handle_services_list)
                app.router.add_get("/api/services/available", subject.handle_available_services)
                app.router.add_get("/api/services/info/{name}", subject.handle_service_info)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    async def test_service_streams_preserve_authorization_headers_and_event_payloads(self):
        cases = (
            ("/api/services", "get_all_services_status", "services_list", False),
            ("/api/services/available", "get_all_available_services", "available_services", False),
            ("/api/services/info/nginx?type=systemd", "get_service_info", "service_info", True),
        )
        for path, provider_name, event, is_async in cases:
            with self.subTest(path=path):
                payload = {"name": "nginx", "status": "running"}
                provider = AsyncMock(return_value=payload) if is_async else Mock(return_value=payload)
                with patch.object(self.api, provider_name, provider):
                    anonymous = await self.client.get(path)
                    self.assertEqual(anonymous.status, 401)
                    self.assertNotIn("text/event-stream", anonymous.headers.get("Content-Type", ""))
                    provider.assert_not_called()
                    response = await self.client.get(path, headers={"X-Test-User": "owner"})
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.headers["Content-Type"], "text/event-stream")
                    self.assertEqual(response.headers["Cache-Control"], "no-cache")
                    self.assertEqual(response.headers["Connection"], "keep-alive")
                    self.assertEqual(await response.text(), f"event: {event}\ndata: {json.dumps(payload)}\n\n")
                    if is_async:
                        provider.assert_awaited_once_with("nginx", "systemd")
                    else:
                        provider.assert_called_once_with()

    async def test_anonymous_and_readonly_users_cannot_read_history(self):
        for path in ("/operations", "/api/operations", "/api/operations/stream?ids=1"):
            for user in ("", "reader"):
                response = await self.client.get(path, headers={"X-Test-User": user}, allow_redirects=False)
                self.assertIn(response.status, (302, 401, 403))
                self.assertNotIn("Server response", await response.text())

    async def test_owner_and_admin_have_access_without_cache(self):
        with patch.object(operations, "history", return_value=([], None)), patch.object(Node, "all", return_value=asyncio.sleep(0, result=[])):
            response = await self.client.get("/operations", headers={"X-Test-User": "owner"})
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertIn("Operations center", await response.text())
        with patch.object(operations, "history", return_value=([], None)):
            response = await self.client.get("/api/operations", headers={"X-Test-User": "admin"})
            self.assertEqual(response.status, 200)
            envelope = await response.json()
            self.assertEqual(json.loads(decrypt_web_fixture(envelope["d"])), {"operations": [], "next_before": None})

    async def test_bad_filters_return_400(self):
        for path in ("/operations", "/api/operations"):
            response = await self.client.get(path + "?before=-1", headers={"X-Test-User": "admin"})
            self.assertEqual(response.status, 400)

    async def test_stream_returns_card_updates_and_stops_on_shutdown(self):
        row = SimpleNamespace(id=8, node_id=1, command="traffic", status="finished", requested_by=42,
                              payload="{}", result=json.dumps("<script>sample</script>"), created_at=1, updated_at=2)
        query = Mock()
        query.order_by = AsyncMock(return_value=[row])
        with patch.object(NodeOperation, "filter", return_value=query) as select:
            response = await self.client.get("/api/operations/stream?ids=8", headers={"X-Test-User": "admin"})
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertEqual(await response.content.readline(), b"event: operations\n")
            data = (await response.content.readline()).decode()[6:]
            self.assertNotIn("<script>", data)
            updates = json.loads(decrypt_web_fixture(json.loads(data)["d"]))
            self.assertEqual(updates[0]["id"], 8)
            self.assertEqual(updates[0]["result"], "<script>sample</script>")
            self.assertNotIn("payload", updates[0])
            select.assert_called_once_with(id__in=[8])
            self.shutdown.set()
            await asyncio.wait_for(response.read(), timeout=2)

    async def test_stream_rejects_invalid_or_excessive_ids(self):
        for ids in ("", "-1", "abc", str(2**63), ",".join(str(i) for i in range(1, 52))):
            response = await self.client.get("/api/operations/stream?ids=" + ids, headers={"X-Test-User": "admin"})
            self.assertEqual(response.status, 400)

    async def test_stream_rechecks_permissions_after_connection(self):
        self.auth.get_current_user.side_effect = [{"id": 2, "role": "admins"}, None]
        response = await self.client.get("/api/operations/stream?ids=8", headers={"X-Test-User": "admin"})
        self.assertIn("event: session_expired", await response.text())

    async def test_operation_assets_require_admin_even_through_static_aliases(self):
        for path in ("/static/js/operations.js", "/static/css/operations.css", "/static/js//operations.js"):
            response = await self.client.get(path)
            self.assertEqual(response.status, 401)
            response = await self.client.get(path, headers={"X-Test-User": "reader"})
            self.assertEqual(response.status, 403)
        response = await self.client.get("/static/js/operations.js", headers={"X-Test-User": "admin"})
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertIn("initOperations", await response.text())
        response = await self.client.get("/static/js/panel_navigation.js", headers={"X-Test-User": "reader"})
        self.assertEqual(response.status, 200)

    async def test_initial_history_encrypts_private_display_fields(self):
        row = SimpleNamespace(id=8, node_id=1, command="traffic", status="finished", requested_by=7654321,
                              payload="{}", result=json.dumps("private output"), created_at=1, updated_at=2)
        with patch.object(operations, "history", return_value=([row], None)), patch.object(
            Node, "all", return_value=asyncio.sleep(0, result=[SimpleNamespace(id=1, name="private node")]),
        ):
            response = await self.client.get("/operations", headers={"X-Test-User": "owner"})
            html = await response.text()
            self.assertEqual(response.status, 200)
            for private in ("private node", "private output", "7654321"):
                self.assertNotIn(private, html)
            self.assertIn("data-operation-encrypted", html)


if __name__ == "__main__":
    unittest.main()
