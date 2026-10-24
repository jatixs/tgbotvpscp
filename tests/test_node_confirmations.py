import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch


ROOT = Path(__file__).resolve().parents[1]
TOKEN = "a" * 32


class NodeConfirmationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        dependencies = {
            name: MagicMock()
            for name in (
                "aiohttp", "aiogram", "aiogram.filters", "aiogram.fsm",
                "aiogram.fsm.context", "aiogram.fsm.state", "aiogram.types",
                "core", "core.auth", "core.i18n", "core.keyboards",
                "core.messaging", "core.shared_state", "core.utils",
            )
        }
        dependencies["aiogram.fsm.state"].StatesGroup = object
        spec = importlib.util.spec_from_file_location("node_confirmation_subject", ROOT / "modules" / "nodes.py")
        if spec is None or spec.loader is None:
            self.fail("Unable to load node management module")
        subject = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, dependencies):
            spec.loader.exec_module(subject)
        self.node = {"name": "<Test node>", "services": [{"name": "my_service", "type": "docker"}]}
        self.db = SimpleNamespace(
            get_node_by_token=AsyncMock(return_value=self.node),
            update_node_task=AsyncMock(),
            update_node_extra=AsyncMock(),
        )
        replacements = {
            "config": SimpleNamespace(ADMIN_USER_ID=1),
            "nodes_db": self.db,
            "get_user_lang": lambda user_id: "en",
            "is_allowed": Mock(return_value=True),
            "_": lambda key, lang, **values: key + str(values),
            "InlineKeyboardButton": lambda **values: SimpleNamespace(**values),
            "InlineKeyboardMarkup": lambda **values: SimpleNamespace(**values),
            "get_back_keyboard": lambda lang, target: target,
            "asyncio": SimpleNamespace(sleep=AsyncMock()),
            "cq_node_services": AsyncMock(),
        }
        for name, value in replacements.items():
            setattr(subject, name, value)
        self.env = vars(subject)

    def callback(self, data, user_id=1):
        return SimpleNamespace(
            data=data,
            from_user=SimpleNamespace(id=user_id),
            answer=AsyncMock(),
            message=SimpleNamespace(edit_text=AsyncMock(), edit_reply_markup=AsyncMock()),
        )

    async def test_reboot_and_update_require_confirmation(self):
        for command in ("reboot", "update"):
            with self.subTest(command=command):
                callback = self.callback(f"node_cmd_{TOKEN}_{command}")
                await self.env["cq_node_command"](callback)
                self.db.update_node_task.assert_not_awaited()
                self.db.update_node_extra.assert_not_awaited()
                self.assertIn("&lt;Test node&gt;", callback.message.edit_text.call_args.args[0])
                rows = callback.message.edit_text.call_args.kwargs["reply_markup"].inline_keyboard
                self.assertEqual(rows[0][0].callback_data, f"node_run_{TOKEN}_{command}")
                self.assertEqual(rows[1][0].callback_data, f"node_select_{TOKEN}")
                self.assertEqual(rows[0][0].style, "success")
                self.assertEqual(rows[1][0].style, "danger")
                self.assertLessEqual(len(rows[0][0].callback_data.encode()), 64)

    async def test_confirmed_commands_queue_correct_task(self):
        for command in ("reboot", "update"):
            with self.subTest(command=command):
                self.db.update_node_task.reset_mock()
                self.db.update_node_extra.reset_mock()
                callback = self.callback(f"node_run_{TOKEN}_{command}")
                await self.env["cq_node_command_confirm"](callback)
                callback.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)
                self.db.update_node_task.assert_awaited_once_with(TOKEN, {"command": command, "user_id": 1})
                if command == "reboot":
                    self.db.update_node_extra.assert_awaited_once_with(TOKEN, "is_restarting", True)
                else:
                    self.db.update_node_extra.assert_not_awaited()

    async def test_confirmed_commands_recheck_permissions_and_node(self):
        for command in ("reboot", "update"):
            with self.subTest(command=command):
                callback = self.callback(f"node_run_{TOKEN}_{command}", user_id=2)
                await self.env["cq_node_command_confirm"](callback)
                self.db.update_node_task.assert_not_awaited()
                self.db.update_node_extra.assert_not_awaited()
        self.db.get_node_by_token.return_value = None
        await self.env["cq_node_command_confirm"](self.callback(f"node_run_{TOKEN}_reboot"))
        self.db.update_node_task.assert_not_awaited()

    async def test_confirmation_route_rejects_other_commands(self):
        await self.env["cq_node_command_confirm"](self.callback(f"node_run_{TOKEN}_resetuptime"))
        self.db.update_node_task.assert_not_awaited()

    async def test_service_restart_requires_confirmation(self):
        callback = self.callback(f"nsa_{TOKEN}_my_service_d_restart")
        await self.env["cq_node_service_action"](callback)
        self.db.update_node_task.assert_not_awaited()
        rows = callback.message.edit_text.call_args.kwargs["reply_markup"].inline_keyboard
        self.assertEqual(rows[0][0].callback_data, f"nsc_{TOKEN}_my_service_d_restart")
        self.assertEqual(rows[1][0].callback_data, f"node_services_{TOKEN}")
        self.assertLessEqual(len(rows[0][0].callback_data.encode()), 64)

    async def test_confirmed_service_restart_preserves_target(self):
        callback = self.callback(f"nsc_{TOKEN}_my_service_d_restart")
        await self.env["cq_node_service_confirm"](callback)
        self.db.update_node_task.assert_awaited_once_with(TOKEN, {
            "command": "service_action", "service": "my_service", "action": "restart",
            "type": "docker", "user_id": 1,
        })
        self.env["cq_node_services"].assert_awaited_once_with(callback, node_token=TOKEN)

    async def test_service_confirmation_rechecks_target_and_permission(self):
        for data, user_id in (
            (f"nsc_{TOKEN}_my_service_d_restart", 2),
            (f"nsc_{TOKEN}_missing_d_restart", 1),
            (f"nsc_{TOKEN}_my_service_d_stop", 1),
        ):
            with self.subTest(data=data, user_id=user_id):
                await self.env["cq_node_service_confirm"](self.callback(data, user_id))
                self.db.update_node_task.assert_not_awaited()

    async def test_service_start_and_stop_are_unchanged(self):
        for action in ("start", "stop"):
            with self.subTest(action=action):
                self.db.update_node_task.reset_mock()
                callback = self.callback(f"nsa_{TOKEN}_my_service_d_{action}")
                await self.env["cq_node_service_action"](callback)
                self.db.update_node_task.assert_awaited_once()
                callback.message.edit_text.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
