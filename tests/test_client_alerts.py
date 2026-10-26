"""
tests/test_client_alerts.py - Comprehensive tests for client alerts features:
settings (mute all messages, mute broadcasts, per-node mute), media buffering,
keyboard generation, pinning, broadcast deletion, and service message filtering.
"""

import os
import sys
import types
import unittest
from base64 import b64encode
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATA_ENCRYPTION_KEY", b64encode(b"0" * 32).decode())
os.environ.setdefault("TG_BOT_TOKEN", "123456789:TEST_BOT_TOKEN")
os.environ.setdefault("TG_ADMIN_ID", "12345")
os.environ.setdefault("ALERT_BOT_TOKEN", "987654321:TEST_ALERT_TOKEN")

modules_to_mock = [
    "aiohttp", "aiohttp.web", "argon2", "argon2.exceptions", "aiosqlite",
    "requests", "PIL", "PIL.Image", "qrcode",
    "netifaces", "psutil", "sentry_sdk", "yaml", "docker", "asyncssh", "tortoise",
]

for m in modules_to_mock:
    if m not in sys.modules:
        mod = MagicMock()
        mod.__path__ = []
        mod.__spec__ = types.SimpleNamespace(name=m, origin=None, submodule_search_locations=[])
        sys.modules[m] = mod


class MockInlineKeyboardButton:
    def __init__(self, text="", callback_data=None, url=None, **kwargs):
        self.text = text
        self.callback_data = callback_data
        self.url = url


class MockKeyboardButton:
    def __init__(self, text="", **kwargs):
        self.text = text


class MockReplyKeyboardMarkup:
    def __init__(self, keyboard=None, **kwargs):
        self.keyboard = keyboard or []


class MockInlineKeyboardMarkup:
    def __init__(self, inline_keyboard=None, **kwargs):
        self.inline_keyboard = inline_keyboard or []


class MockStatesGroup:
    pass


mock_aiogram = MagicMock()
mock_types = MagicMock()
mock_types.InlineKeyboardButton = MockInlineKeyboardButton
mock_types.InlineKeyboardMarkup = MockInlineKeyboardMarkup
mock_types.KeyboardButton = MockKeyboardButton
mock_types.ReplyKeyboardMarkup = MockReplyKeyboardMarkup
mock_aiogram.types = mock_types

mock_dp = MagicMock()
mock_dp.message.return_value = lambda f: f
mock_dp.callback_query.return_value = lambda f: f
mock_dp.message_reaction.return_value = lambda f: f
mock_dp.poll_answer.return_value = lambda f: f
mock_aiogram.Dispatcher.return_value = mock_dp
mock_aiogram.fsm.state.StatesGroup = MockStatesGroup
mock_aiogram.fsm.state.State = MagicMock

sys.modules["aiogram"] = mock_aiogram
sys.modules["aiogram.types"] = mock_types
sys.modules["aiogram.filters"] = mock_aiogram.filters
sys.modules["aiogram.fsm"] = mock_aiogram.fsm
sys.modules["aiogram.fsm.context"] = mock_aiogram.fsm.context
sys.modules["aiogram.fsm.state"] = mock_aiogram.fsm.state
sys.modules["aiogram.fsm.storage"] = mock_aiogram.fsm.storage
sys.modules["aiogram.fsm.storage.memory"] = mock_aiogram.fsm.storage.memory

import core  # noqa: E402
from core import config  # noqa: E402
core.nodes_db = MagicMock()
sys.modules["core.nodes_db"] = core.nodes_db

from modules.client_alerts import (  # noqa: E402
    _broadcast_confirm,
    _broadcast_message_received,
    _cq_client_cancel_mute_all,
    _cq_client_confirm_mute_all,
    _cq_client_settings_toggle_all,
    _cq_client_settings_toggle_broadcasts,
    _cq_view_broadcast,
    _delete_broadcast_for_all,
    _get_alert_panel_keyboard,
    _get_broadcast_confirm_keyboard,
    _get_client_main_keyboard,
    _get_client_settings_keyboard,
    _load_broadcast_history,
    _load_polls_registry,
    _record_broadcast,
    _render_broadcast_confirm_text,
    _save_broadcast_history,
    _save_polls_registry,
    _send_payload_via_alert_bot,
    alert_message_handler,
    alert_poll_answer_handler,
    alert_reaction_handler,
    broadcast_system_alert,
    is_node_muted_for_user,
    BROADCASTS_FILE,
    POLLS_FILE,
    SUBSCRIBERS_FILE,
)


class ClientAlertsFeatureTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def tearDownClass(cls):
        import contextlib
        import shutil
        for f in [BROADCASTS_FILE, POLLS_FILE, SUBSCRIBERS_FILE]:
            with contextlib.suppress(OSError):
                if os.path.exists(f):
                    os.remove(f)
        config_dir = os.path.dirname(BROADCASTS_FILE)
        with contextlib.suppress(OSError):
            if os.path.exists(config_dir) and not os.listdir(config_dir):
                shutil.rmtree(config_dir, ignore_errors=True)
    def test_render_broadcast_confirm_text(self):
        text_default = _render_broadcast_confirm_text(10, pin=False, silent=False)
        self.assertIn("Получателей: <b>10</b>", text_default)
        self.assertIn("Закрепить у всех: <b>Нет</b>", text_default)
        self.assertIn("Доставка: <b>Со звуком</b>", text_default)
        self.assertIn("Кнопка: <i>не задана</i>", text_default)

        text_custom = _render_broadcast_confirm_text(
            5, pin=True, silent=True, btn_title="Новости", btn_url="https://t.me/news"
        )
        self.assertIn("Закрепить у всех: <b>Да</b>", text_custom)
        self.assertIn("Доставка: <b>Без звука</b>", text_custom)
        self.assertIn("Новости", text_custom)
        self.assertIn("https://t.me/news", text_custom)

    def test_get_broadcast_confirm_keyboard(self):
        kb_default = _get_broadcast_confirm_keyboard(pin=False, silent=False, btn_info=None)
        button_texts = [btn.text for row in kb_default.inline_keyboard for btn in row]
        self.assertIn("📌 Закрепить: НЕТ", button_texts)
        self.assertIn("🔔 Со звуком", button_texts)
        self.assertIn("🔘 Добавить кнопку", button_texts)
        self.assertIn("✅ Отправить всем", button_texts)

        kb_active = _get_broadcast_confirm_keyboard(pin=True, silent=True, btn_info="Ссылка на чат")
        btn_active_texts = [btn.text for row in kb_active.inline_keyboard for btn in row]
        self.assertIn("📌 Закрепить: ДА", btn_active_texts)
        self.assertIn("🔕 Без звука", btn_active_texts)
        self.assertTrue(any("Ссылка на чат" in t for t in btn_active_texts))

    async def test_client_settings_keyboard_mute_all_active(self):
        fake_subscribers = {
            1001: {"name": "User 1", "mute_all": True, "muted_nodes": []}
        }
        with patch("modules.client_alerts._load_subscribers", return_value=fake_subscribers), \
             patch("core.nodes_db.get_all_nodes", AsyncMock(return_value={"tok1": {"name": "Node Alpha"}})):
            kb = await _get_client_settings_keyboard(1001)
            btn_texts = [btn.text for row in kb.inline_keyboard for btn in row]
            callback_datas = [btn.callback_data for row in kb.inline_keyboard for btn in row]

            # Should contain mute_all toggle showing it is ON (muted)
            self.assertIn("cst_toggle_all", callback_datas)
            self.assertTrue(any("Заглушены" in t or "Muted" in t for t in btn_texts))
            # When mute_all is True, sub-toggles (broadcasts, nodes) should be hidden
            self.assertNotIn("cst_toggle_broadcasts", callback_datas)
            self.assertFalse(any("Node Alpha" in t for t in btn_texts))

    async def test_client_settings_keyboard_mute_all_inactive(self):
        fake_subscribers = {
            1002: {"name": "User 2", "mute_all": False, "mute_broadcasts": False, "muted_nodes": ["tok2"]}
        }
        all_nodes = {
            "tok1": {"name": "Node Alpha"},
            "tok2": {"name": "Node Beta"}
        }
        with patch("modules.client_alerts._load_subscribers", return_value=fake_subscribers), \
             patch("core.nodes_db.get_all_nodes", AsyncMock(return_value=all_nodes)):
            kb = await _get_client_settings_keyboard(1002)
            btn_texts = [btn.text for row in kb.inline_keyboard for btn in row]
            callback_datas = [btn.callback_data for row in kb.inline_keyboard for btn in row]

            self.assertIn("cst_toggle_all", callback_datas)
            self.assertTrue(any("Включены" in t or "Active" in t for t in btn_texts))
            # Sub-toggles should be visible
            self.assertIn("cst_toggle_broadcasts", callback_datas)
            self.assertIn("cst_node_tok1", callback_datas)
            self.assertIn("cst_node_tok2", callback_datas)

            # Node Beta should be shown as muted (🔕), Node Alpha as active (🔔)
            self.assertTrue(any("🔕 Node Beta" in t for t in btn_texts))
            self.assertTrue(any("🔔 Node Alpha" in t for t in btn_texts))

    def test_is_node_muted_for_user(self):
        fake_subscribers = {
            2001: {"name": "All Muted", "mute_all": True, "muted_nodes": []},
            2002: {"name": "Node Muted", "mute_all": False, "muted_nodes": ["tok_down"]},
            2003: {"name": "Nothing Muted", "mute_all": False, "muted_nodes": []},
        }
        with patch("modules.client_alerts._load_subscribers", return_value=fake_subscribers):
            # User with mute_all=True has all nodes muted
            self.assertTrue(is_node_muted_for_user(2001, "tok_down"))
            self.assertTrue(is_node_muted_for_user(2001, "tok_random"))

            # User with specific node muted
            self.assertTrue(is_node_muted_for_user(2002, "tok_down"))
            self.assertFalse(is_node_muted_for_user(2002, "tok_other"))

            # User with nothing muted
            self.assertFalse(is_node_muted_for_user(2003, "tok_down"))

    async def test_broadcast_system_alert_skips_muted_all(self):
        fake_subscribers = {
            3001: {"name": "Normal", "mute_all": False},
            3002: {"name": "Muted", "mute_all": True},
        }
        mock_bot = AsyncMock()
        mock_bot.send_message.return_value = MagicMock(message_id=999)

        with patch("modules.client_alerts._load_subscribers", return_value=fake_subscribers), \
             patch("modules.client_alerts.alert_bot", mock_bot):
            await broadcast_system_alert("Внимание: сервер перезагружается")
            # Only user 3001 should receive message
            self.assertEqual(mock_bot.send_message.call_count, 1)
            args, _ = mock_bot.send_message.call_args
            self.assertEqual(args[0], 3001)

    async def test_broadcast_confirm_skips_muted_all_and_muted_broadcasts(self):
        fake_subscribers = {
            4001: {"name": "User 1", "mute_all": False, "mute_broadcasts": False},
            4002: {"name": "User 2", "mute_all": True, "mute_broadcasts": False},
            4003: {"name": "User 3", "mute_all": False, "mute_broadcasts": True},
        }
        mock_callback = AsyncMock()
        mock_callback.from_user.id = int(os.environ["TG_ADMIN_ID"])
        mock_callback.message = AsyncMock()
        mock_state = AsyncMock()
        mock_state.get_data.return_value = {
            "broadcast_payload": {"type": "text", "text": "Тестовое объявление"},
            "broadcast_pin": False,
            "broadcast_silent": False,
        }

        mock_send = AsyncMock(return_value=MagicMock(message_id=101))

        with patch("modules.client_alerts._load_subscribers", return_value=fake_subscribers), \
             patch("modules.client_alerts._send_payload_via_alert_bot", mock_send), \
             patch("modules.client_alerts.alert_bot", AsyncMock()):
            await _broadcast_confirm(mock_callback, mock_state)
            # Only user 4001 should receive the broadcast (4002 has mute_all, 4003 has mute_broadcasts)
            self.assertEqual(mock_send.call_count, 1)
            args, _ = mock_send.call_args
            self.assertEqual(args[0], 4001)

    async def test_toggle_all_shows_warning_dialog(self):
        subscribers = {5001: {"name": "User", "mute_all": False}}
        saved = {}

        def mock_save(data):
            saved.clear()
            saved.update(data)

        mock_callback = AsyncMock()
        mock_callback.from_user.id = 5001
        mock_callback.message = AsyncMock()

        with patch("modules.client_alerts._load_subscribers", return_value=subscribers), \
             patch("modules.client_alerts._save_subscribers", side_effect=mock_save), \
             patch("modules.client_alerts._get_client_settings_keyboard", AsyncMock(return_value=MagicMock())):
            await _cq_client_settings_toggle_all(mock_callback)
            # Should NOT mutate mute_all yet
            self.assertFalse(saved.get(5001, {}).get("mute_all", False))
            # Should edit message to display warning with OK and Cancel buttons
            mock_callback.message.edit_text.assert_called_once()
            args, kwargs = mock_callback.message.edit_text.call_args
            self.assertIn("тишины", args[0])
            buttons = [b.callback_data for row in kwargs["reply_markup"].inline_keyboard for b in row]
            self.assertIn("cst_confirm_mute_all", buttons)
            self.assertIn("cst_cancel_mute_all", buttons)
            mock_callback.answer.assert_called_once()

    async def test_confirm_mute_all_callback(self):
        subscribers = {5001: {"name": "User", "mute_all": False}}
        saved = {}

        def mock_save(data):
            saved.clear()
            saved.update(data)

        mock_callback = AsyncMock()
        mock_callback.from_user.id = 5001
        mock_callback.message = AsyncMock()

        with patch("modules.client_alerts._load_subscribers", return_value=subscribers), \
             patch("modules.client_alerts._save_subscribers", side_effect=mock_save), \
             patch("modules.client_alerts._get_client_settings_keyboard", AsyncMock(return_value=MagicMock())):
            await _cq_client_confirm_mute_all(mock_callback)
            # Should set mute_all to True
            self.assertTrue(saved[5001]["mute_all"])
            mock_callback.message.edit_text.assert_called_once()
            mock_callback.answer.assert_called_once()

    async def test_cancel_mute_all_callback(self):
        subscribers = {5001: {"name": "User", "mute_all": False}}
        saved = {}

        def mock_save(data):
            saved.clear()
            saved.update(data)

        mock_callback = AsyncMock()
        mock_callback.from_user.id = 5001
        mock_callback.message = AsyncMock()

        with patch("modules.client_alerts._load_subscribers", return_value=subscribers), \
             patch("modules.client_alerts._save_subscribers", side_effect=mock_save), \
             patch("modules.client_alerts._get_client_settings_keyboard", AsyncMock(return_value=MagicMock())):
            await _cq_client_cancel_mute_all(mock_callback)
            # Should NOT save mute_all as True
            self.assertFalse(saved.get(5001, {}).get("mute_all", False))
            mock_callback.message.edit_text.assert_called_once()
            mock_callback.answer.assert_called_once()

    async def test_toggle_all_unmutes_directly_when_already_muted(self):
        subscribers = {5001: {"name": "User", "mute_all": True}}
        saved = {}

        def mock_save(data):
            saved.clear()
            saved.update(data)

        mock_callback = AsyncMock()
        mock_callback.from_user.id = 5001
        mock_callback.message = AsyncMock()

        with patch("modules.client_alerts._load_subscribers", return_value=subscribers), \
             patch("modules.client_alerts._save_subscribers", side_effect=mock_save), \
             patch("modules.client_alerts._get_client_settings_keyboard", AsyncMock(return_value=MagicMock())):
            await _cq_client_settings_toggle_all(mock_callback)
            # Should toggle back to False directly without warning
            self.assertFalse(saved[5001]["mute_all"])
            mock_callback.message.edit_reply_markup.assert_called_once()
            mock_callback.answer.assert_called_once()

    async def test_client_alerts_uses_main_bot_language(self):
        fake_subscribers = {7001: {"name": "User", "mute_all": False}}
        with patch("modules.client_alerts.get_user_lang", return_value="en"), \
             patch("modules.client_alerts._load_subscribers", return_value=fake_subscribers), \
             patch("core.nodes_db.get_all_nodes", AsyncMock(return_value={})):
            kb = await _get_client_settings_keyboard(7001)
            btn_texts = [btn.text for row in kb.inline_keyboard for btn in row]
            self.assertTrue(any("All messages: Active" in t for t in btn_texts))

            main_kb = _get_client_main_keyboard()
            # In English, settings button is Settings
            main_btn = main_kb.keyboard[0][0].text
            self.assertIn("Settings", main_btn)

    async def test_toggle_broadcasts_callback(self):
        subscribers = {6001: {"name": "User", "mute_broadcasts": False}}
        saved = {}

        def mock_save(data):
            saved.clear()
            saved.update(data)

        mock_callback = AsyncMock()
        mock_callback.from_user.id = 6001
        mock_callback.message = AsyncMock()

        with patch("modules.client_alerts._load_subscribers", return_value=subscribers), \
             patch("modules.client_alerts._save_subscribers", side_effect=mock_save), \
             patch("modules.client_alerts._get_client_settings_keyboard", AsyncMock(return_value=MagicMock())):
            await _cq_client_settings_toggle_broadcasts(mock_callback)
            self.assertTrue(saved[6001]["mute_broadcasts"])
            mock_callback.answer.assert_called_once()

    async def test_send_payload_caching(self):
        mock_bot = AsyncMock()
        sent_message = MagicMock()
        sent_photo = MagicMock()
        sent_photo.file_id = "alert_bot_cached_file_id"
        sent_message.photo = [sent_photo]
        mock_bot.send_photo.return_value = sent_message

        payload = {
            "type": "photo",
            "media_bytes": b"fake_image_bytes",
            "filename": "test.jpg",
            "file_id": "original_main_file_id",
            "caption": "Test Photo"
        }

        with patch("modules.client_alerts.alert_bot", mock_bot):
            # First send: sends media bytes and caches file_id
            await _send_payload_via_alert_bot(12345, payload)
            self.assertEqual(payload.get("cached_file_id"), "alert_bot_cached_file_id")

            # Second send: should use cached_file_id directly
            await _send_payload_via_alert_bot(67890, payload)
            call_args = mock_bot.send_photo.call_args_list
            self.assertEqual(len(call_args), 2)
            self.assertEqual(call_args[1].args[1], "alert_bot_cached_file_id")

    async def test_broadcast_deletion(self):
        history_store = []

        def save_h(h):
            history_store.clear()
            history_store.extend(h)

        mock_bot = AsyncMock()
        mock_bot.unpin_chat_message.return_value = True
        mock_bot.unpin_all_chat_messages.return_value = True
        mock_bot.delete_message.return_value = True

        with patch("modules.client_alerts.alert_bot", mock_bot), \
             patch("modules.client_alerts._load_broadcast_history", side_effect=lambda: list(history_store)), \
             patch("modules.client_alerts._save_broadcast_history", side_effect=save_h):
            bc_id = _record_broadcast("Проверочная рассылка", {111: 501, 222: 502}, is_pinned=True)
            self.assertTrue(bc_id.startswith("bc_"))

            del_ok, del_fail = await _delete_broadcast_for_all(bc_id)
            self.assertEqual(del_ok, 2)
            self.assertEqual(del_fail, 0)
            self.assertEqual(mock_bot.unpin_chat_message.call_count, 2)
            self.assertEqual(mock_bot.unpin_all_chat_messages.call_count, 2)
            # 2 messages + 2 service messages (mid+1) = 4 delete calls
            self.assertEqual(mock_bot.delete_message.call_count, 4)

    async def test_broadcast_deletion_unpinned(self):
        history_store = []

        def save_h(h):
            history_store.clear()
            history_store.extend(h)

        mock_bot = AsyncMock()
        mock_bot.delete_message.return_value = True

        with patch("modules.client_alerts.alert_bot", mock_bot), \
             patch("modules.client_alerts._load_broadcast_history", side_effect=lambda: list(history_store)), \
             patch("modules.client_alerts._save_broadcast_history", side_effect=save_h):
            bc_id = _record_broadcast("Обычная рассылка", {111: 601, 222: 602}, is_pinned=False)

            del_ok, del_fail = await _delete_broadcast_for_all(bc_id)
            self.assertEqual(del_ok, 2)
            self.assertEqual(del_fail, 0)
            # When unpinned, NO unpin calls and only 2 delete calls (no mid+1 bubble calls)
            mock_bot.unpin_chat_message.assert_not_called()
            mock_bot.unpin_all_chat_messages.assert_not_called()
            self.assertEqual(mock_bot.delete_message.call_count, 2)

    async def test_pinned_service_message_ignored(self):
        mock_msg = MagicMock()
        mock_msg.pinned_message = MagicMock()
        mock_msg.answer = AsyncMock()
        mock_msg.delete = AsyncMock()

        with patch("modules.client_alerts.alert_bot", MagicMock()):
            await alert_message_handler(mock_msg)
            mock_msg.answer.assert_not_called()
            mock_msg.delete.assert_called_once()

    async def test_broadcast_unsupported_type_rejected(self):
        mock_msg = MagicMock()
        mock_msg.text = None
        mock_msg.caption = None
        mock_msg.photo = None
        mock_msg.video = None
        mock_msg.audio = None
        mock_msg.document = None
        mock_msg.voice = None
        mock_msg.video_note = None
        mock_msg.sticker = None
        mock_msg.animation = None
        mock_msg.poll = None
        mock_msg.location = None
        mock_msg.venue = None
        mock_msg.contact = None
        mock_msg.dice = None
        mock_msg.html_text = None
        mock_msg.caption_entities = None
        mock_msg.answer = AsyncMock()
        mock_state = AsyncMock()

        await _broadcast_message_received(mock_msg, mock_state)
        # Should NOT save to state
        mock_state.update_data.assert_not_called()
        # Should reply with unsupported type error
        mock_msg.answer.assert_called_once()
        args, _ = mock_msg.answer.call_args
        self.assertIn("не поддерживается", args[0])

    async def test_send_poll_payload(self):
        mock_bot = AsyncMock()
        mock_bot.send_poll.return_value = MagicMock(message_id=777)
        poll_payload = {
            "type": "poll",
            "question": "Все работает?",
            "options": ["Да", "Нет"],
            "is_anonymous": True,
        }
        with patch("modules.client_alerts.alert_bot", mock_bot):
            res = await _send_payload_via_alert_bot(12345, poll_payload)
            self.assertEqual(res.message_id, 777)
            mock_bot.send_poll.assert_called_once()

    async def test_reaction_handler_new_and_removed(self):
        mock_main_bot = AsyncMock()
        mock_main_module = MagicMock(bot=mock_main_bot)

        mock_user = MagicMock(id=555123, full_name="Alice User", username="alice", is_bot=False)
        mock_emoji_type = MagicMock(emoji="🔥", custom_emoji_id=None)
        mock_event_new = MagicMock(
            user=mock_user,
            message_id=9876,
            new_reaction=[mock_emoji_type],
            old_reaction=[],
        )

        with patch.dict(sys.modules, {"bot": mock_main_module}):
            await alert_reaction_handler(mock_event_new)
            mock_main_bot.send_message.assert_called_once()
            call_args = mock_main_bot.send_message.call_args[0]
            self.assertEqual(call_args[0], config.ADMIN_USER_ID)
            self.assertIn("Реакция на сообщение", call_args[1])
            self.assertIn("🔥", call_args[1])
            self.assertIn("Alice User", call_args[1])

        mock_main_bot.reset_mock()
        mock_event_removed = MagicMock(
            user=mock_user,
            message_id=9876,
            new_reaction=[],
            old_reaction=[mock_emoji_type],
        )

        with patch.dict(sys.modules, {"bot": mock_main_module}):
            await alert_reaction_handler(mock_event_removed)
            mock_main_bot.send_message.assert_called_once()
            call_args = mock_main_bot.send_message.call_args[0]
            self.assertIn("Реакция снята", call_args[1])
            self.assertIn("🔥", call_args[1])

    async def test_poll_answer_handler_and_aggregated_results(self):
        bc_id = "bc_test_poll"
        _save_broadcast_history([{
            "id": bc_id,
            "timestamp": 1234567.0,
            "date_str": "26.10 21:00",
            "preview": "Опрос: Довольны ли вы скоростью?",
            "sent": {"444111": 7001},
            "is_pinned": False,
            "reactions": {},
            "poll": {
                "question": "Довольны ли вы скоростью?",
                "options": ["Да", "Нет", "Частично"],
                "votes": {},
            }
        }])
        _save_polls_registry({
            "poll_id_999": {
                "bc_id": bc_id,
                "user_id": 444111,
                "message_id": 7001,
                "question": "Довольны ли вы скоростью?",
                "options": ["Да", "Нет", "Частично"]
            }
        })

        mock_main_bot = AsyncMock()
        mock_main_module = MagicMock(bot=mock_main_bot)
        mock_user = MagicMock(id=444111, full_name="Bob Voter", username="bob", is_bot=False)

        # 1. Client votes for "Да" (index 0)
        mock_answer_vote = MagicMock(
            poll_id="poll_id_999",
            user=mock_user,
            option_ids=[0]
        )

        with patch.dict(sys.modules, {"bot": mock_main_module}):
            await alert_poll_answer_handler(mock_answer_vote)
            mock_main_bot.send_message.assert_called_once()
            call_args = mock_main_bot.send_message.call_args[0]
            self.assertIn("Ответ в опросе", call_args[1])
            self.assertIn("Да", call_args[1])
            self.assertIn("Bob Voter", call_args[1])

        history = _load_broadcast_history()
        bc = next(b for b in history if b["id"] == bc_id)
        self.assertEqual(bc["poll"]["votes"].get("444111"), [0])

        # 2. Check _cq_view_broadcast displays aggregated stats
        mock_cq = AsyncMock()
        mock_cq.from_user.id = config.ADMIN_USER_ID
        mock_cq.data = f"alert_view_bc_{bc_id}"
        mock_cq.message.edit_text = AsyncMock()

        await _cq_view_broadcast(mock_cq)
        mock_cq.message.edit_text.assert_called_once()
        text_shown = mock_cq.message.edit_text.call_args[0][0]
        self.assertIn("Результаты опроса:", text_shown)
        self.assertIn("Да: <b>1</b> (100.0%)", text_shown)
        self.assertIn("Всего проголосовало: <b>1</b>", text_shown)

        # 3. Client retracts vote
        mock_main_bot.reset_mock()
        mock_answer_retract = MagicMock(
            poll_id="poll_id_999",
            user=mock_user,
            option_ids=[]
        )

        with patch.dict(sys.modules, {"bot": mock_main_module}):
            await alert_poll_answer_handler(mock_answer_retract)
            mock_main_bot.send_message.assert_called_once()
            call_args = mock_main_bot.send_message.call_args[0]
            self.assertIn("Отзыв голоса в опросе", call_args[1])

        history = _load_broadcast_history()
        bc = next(b for b in history if b["id"] == bc_id)
        self.assertNotIn("444111", bc["poll"]["votes"])

    def test_alert_panel_keyboard_localization(self):
        """Test Alert Module control panel keyboards in ru and en."""
        kb_ru = _get_alert_panel_keyboard("ru")
        ru_texts = [btn.text for row in kb_ru.inline_keyboard for btn in row]
        self.assertIn("📣 Рассылка", ru_texts)
        self.assertIn("🔙 Назад в меню", ru_texts)

        kb_en = _get_alert_panel_keyboard("en")
        en_texts = [btn.text for row in kb_en.inline_keyboard for btn in row]
        self.assertIn("📣 Broadcast", en_texts)
        self.assertIn("🔙 Back to menu", en_texts)

    async def test_client_bot_settings_language_toggle(self):
        """Test subscriber language toggle in Alert Bot."""
        fake_subscribers = {
            777: {"name": "Test User", "mute_all": False, "mute_broadcasts": False, "muted_nodes": [], "lang": "ru"}
        }
        with patch("modules.client_alerts._load_subscribers", return_value=fake_subscribers), \
             patch("core.nodes_db.get_all_nodes", AsyncMock(return_value={})):
            kb = await _get_client_settings_keyboard(777)
            texts = [btn.text for row in kb.inline_keyboard for btn in row]
            self.assertIn("🌐 Язык: 🇷🇺 Русский", texts)

        fake_subscribers_en = {
            777: {"name": "Test User", "mute_all": False, "mute_broadcasts": False, "muted_nodes": [], "lang": "en"}
        }
        with patch("modules.client_alerts._load_subscribers", return_value=fake_subscribers_en), \
             patch("core.nodes_db.get_all_nodes", AsyncMock(return_value={})):
            kb_en = await _get_client_settings_keyboard(777)
            texts_en = [btn.text for row in kb_en.inline_keyboard for btn in row]
            self.assertIn("🌐 Language: 🇬🇧 English", texts_en)


if __name__ == "__main__":
    unittest.main()
