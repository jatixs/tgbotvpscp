"""
modules/client_alerts.py — Gateway Bot / Alert System (optional module).

Architecture:
  • alert_bot  — Secondary Telegram bot (gateway for clients).
    Clients send messages to it → messages are forwarded to the administrator via main bot.
  • main bot   — Receives incoming tickets; administrator manages via inline menu:
      ↳ "📣 Write alert" button (cat_tools) → opens control panel
      ↳ "📣 Broadcast" → FSM broadcast flow
      ↳ "👥 Subscribers" → subscriber list
      ↳ "💬 Reply" under ticket → FSM reply flow

Activation: Set ALERT_BOT_TOKEN=<token> environment variable.
If the token is not set, the module loads, but alert_bot does not start.

Subscribers Storage: config/alert_subscribers.json (simple JSON file).
"""

import asyncio
import io
import json
import logging
import os
import time

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BufferedInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyParameters,
)

from core import config
from core.i18n import I18nFilter, _, get_user_lang, log_text

# ─── Constants ────────────────────────────────────────────────────────────────

ALERT_BOT_TOKEN: str | None = os.getenv("ALERT_BOT_TOKEN")

# Path to JSON file with subscriber IDs
SUBSCRIBERS_FILE = os.path.join(config.CONFIG_DIR, "alert_subscribers.json")

# Dictionary for anti-flood: user_id -> timestamp
_user_last_message_time: dict[int, float] = {}
_USER_FLOOD_STATE_TTL = 600
_MAX_USER_FLOOD_STATES = 20_000
_last_flood_state_cleanup = 0.0

# ─── FSM States for main bot ──────────────────────────────────────────────────


class BroadcastStates(StatesGroup):
    """FSM: administrator broadcasts to all Alert Bot subscribers."""
    waiting_broadcast_message = State()
    waiting_broadcast_button = State()


class ReplyStates(StatesGroup):
    """FSM: administrator replies to a specific Alert Bot user."""
    waiting_reply_text = State()


# ─── Subscribers Storage ────────────────────────────────────────────────────

def _load_subscribers() -> dict[int, dict]:
    """Load subscribers dictionary from JSON file. Format: {user_id: {"name": user_name, "mute_all": bool, "muted_nodes": list}}"""
    try:
        if os.path.exists(SUBSCRIBERS_FILE):
            with open(SUBSCRIBERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    migrated = {int(uid): {"name": f"ID {uid}", "mute_all": False, "muted_nodes": []} for uid in data}
                    _save_subscribers(migrated)
                    return migrated
                elif isinstance(data, dict):
                    migrated = {}
                    updated = False
                    for k, v in data.items():
                        if isinstance(v, str):
                            migrated[int(k)] = {"name": v, "mute_all": False, "muted_nodes": []}
                            updated = True
                        else:
                            migrated[int(k)] = v
                    if updated:
                        _save_subscribers(migrated)
                    return migrated
    except Exception as e:
        logging.warning(f"[client_alerts] Failed to load subscribers: {e}")
    return {}


def _save_subscribers(subscribers: dict[int, dict]) -> None:
    """Save subscribers dictionary to JSON file."""
    try:
        os.makedirs(os.path.dirname(SUBSCRIBERS_FILE), exist_ok=True)
        with open(SUBSCRIBERS_FILE, "w", encoding="utf-8") as f:
            json.dump(subscribers, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"[client_alerts] Failed to save subscribers: {e}")


async def _add_subscriber(user_id: int, user_name: str) -> bool:
    """Add a subscriber or update name. Returns True if added for the first time."""
    subscribers = _load_subscribers()
    is_new = user_id not in subscribers
    if is_new:
        subscribers[user_id] = {"name": user_name, "mute_all": False, "mute_broadcasts": False, "muted_nodes": []}
        _save_subscribers(subscribers)
    elif subscribers[user_id].get("name") != user_name:
        subscribers[user_id]["name"] = user_name
        _save_subscribers(subscribers)
    return is_new


def is_node_muted_for_user(user_id: int, node_token: str) -> bool:
    """Check if a user has muted a specific node (or all of them at once)."""
    subscribers = _load_subscribers()
    s_data = subscribers.get(user_id)
    if not s_data:
        return False
    if s_data.get("mute_all", False):
        return True
    if node_token in s_data.get("muted_nodes", []):
        return True
    return False


BROADCASTS_FILE = os.path.join(config.CONFIG_DIR, "alert_broadcasts.json")


def _load_broadcast_history() -> list[dict]:
    """Loads broadcast history list from JSON file."""
    try:
        if os.path.exists(BROADCASTS_FILE):
            with open(BROADCASTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
    except Exception as e:
        logging.warning(f"[client_alerts] Failed to load broadcast history: {e}")
    return []


def _save_broadcast_history(history: list[dict]) -> None:
    """Saves broadcast history list to JSON file (retaining last 15)."""
    try:
        os.makedirs(os.path.dirname(BROADCASTS_FILE), exist_ok=True)
        trimmed = history[-15:]
        with open(BROADCASTS_FILE, "w", encoding="utf-8") as f:
            json.dump(trimmed, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"[client_alerts] Failed to save broadcast history: {e}")


def _record_broadcast(preview: str, sent_map: dict[int, int], is_pinned: bool = False) -> str:
    """Saves record of sent broadcast and returns broadcast_id."""
    import datetime
    bc_id = f"bc_{int(time.time())}"
    now_str = datetime.datetime.now().strftime("%d.%m %H:%M")
    entry = {
        "id": bc_id,
        "timestamp": time.time(),
        "date_str": now_str,
        "preview": (preview[:45] + "…") if len(preview) > 45 else preview,
        "sent": {str(uid): mid for uid, mid in sent_map.items()},
        "is_pinned": is_pinned,
    }
    history = _load_broadcast_history()
    history.append(entry)
    _save_broadcast_history(history)
    return bc_id


async def _delete_broadcast_for_all(broadcast_id: str) -> tuple[int, int]:
    """Deletes messages of a specific broadcast for all subscribers concurrently."""
    if alert_bot is None:
        return 0, 0
    history = _load_broadcast_history()
    target_entry = None
    target_idx = -1
    for idx, entry in enumerate(history):
        if entry.get("id") == broadcast_id:
            target_entry = entry
            target_idx = idx
            break

    if not target_entry:
        return 0, 0

    sent_map = target_entry.get("sent", {})
    is_pinned = target_entry.get("is_pinned", False)

    sem = asyncio.Semaphore(10)

    async def _delete_for_subscriber(uid_str: str, mid: int) -> bool:
        uid = int(uid_str)
        async with sem:
            if is_pinned:
                try:
                    await alert_bot.unpin_chat_message(chat_id=uid, message_id=mid)
                except Exception as unpin_id_err:
                    logging.debug("Unable to unpin message %s for %s: %s", mid, uid, unpin_id_err)
                    try:
                        await alert_bot.unpin_chat_message(chat_id=uid)
                    except Exception as unpin_last_err:
                        logging.debug("Unable to unpin latest message for %s: %s", uid, unpin_last_err)

                try:
                    await alert_bot.unpin_all_chat_messages(chat_id=uid)
                except Exception as unpin_all_err:
                    logging.debug("Unable to unpin all messages for %s: %s", uid, unpin_all_err)

            deleted = False
            try:
                await alert_bot.delete_message(chat_id=uid, message_id=mid)
                deleted = True
            except Exception as e:
                logging.debug("[client_alerts] Could not delete message %s for %s: %s", mid, uid_str, e)

            if is_pinned:
                try:
                    await alert_bot.delete_message(chat_id=uid, message_id=mid + 1)
                except Exception as del_bubble_err:
                    logging.debug("No pin service bubble to delete for %s: %s", uid, del_bubble_err)

            return deleted

    tasks = [
        _delete_for_subscriber(uid_str, mid)
        for uid_str, mid in sent_map.items()
    ]
    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        del_ok = sum(1 for r in results if r is True)
        del_fail = len(results) - del_ok
    else:
        del_ok = 0
        del_fail = 0

    if target_idx >= 0:
        history.pop(target_idx)
        _save_broadcast_history(history)

    return del_ok, del_fail


# ─── Helper Send Functions ─────────────────────────────────────────

async def _extract_message_payload(message: types.Message) -> dict:
    """
    Extracts serializable payload from message for storage in FSM state.
    Downloads media into memory buffer for cross-bot streaming compatibility.
    Stores raw entities for rich text formatting support.
    """
    def dump_entity(e):
        return e.model_dump(exclude_none=True) if hasattr(e, "model_dump") else e.dict(exclude_none=True)

    payload = {}
    
    if message.text:
        payload["type"] = "text"
        payload["text"] = message.text
        if message.entities:
            payload["entities"] = [dump_entity(e) for e in message.entities]
    else:
        payload["caption"] = message.caption or ""
        if message.caption_entities:
            payload["entities"] = [dump_entity(e) for e in message.caption_entities]
            
        async def _download_to_buffer(tg_file, default_name: str) -> None:
            if message.bot:
                try:
                    bio = io.BytesIO()
                    await message.bot.download(tg_file, destination=bio)
                    payload["media_bytes"] = bio.getvalue()
                    payload["filename"] = getattr(tg_file, "file_name", None) or default_name
                except Exception as dl_err:
                    logging.warning(f"[client_alerts] Could not download media buffer: {dl_err}")

        if message.photo:
            payload["type"] = "photo"
            payload["file_id"] = message.photo[-1].file_id
            await _download_to_buffer(message.photo[-1], "photo.jpg")
        elif message.video:
            payload["type"] = "video"
            payload["file_id"] = message.video.file_id
            await _download_to_buffer(message.video, "video.mp4")
        elif message.audio:
            payload["type"] = "audio"
            payload["file_id"] = message.audio.file_id
            await _download_to_buffer(message.audio, "audio.mp3")
        elif message.document:
            payload["type"] = "document"
            payload["file_id"] = message.document.file_id
            await _download_to_buffer(message.document, "document")
        elif message.voice:
            payload["type"] = "voice"
            payload["file_id"] = message.voice.file_id
            await _download_to_buffer(message.voice, "voice.ogg")
        elif message.video_note:
            payload["type"] = "video_note"
            payload["file_id"] = message.video_note.file_id
            await _download_to_buffer(message.video_note, "video_note.mp4")
        elif message.sticker:
            payload["type"] = "sticker"
            payload["file_id"] = message.sticker.file_id
        elif message.animation:
            payload["type"] = "animation"
            payload["file_id"] = message.animation.file_id
            await _download_to_buffer(message.animation, "animation.mp4")
        else:
            payload["type"] = "unsupported"
            try:
                payload["debug"] = str(message.model_dump(exclude_none=True))
            except Exception:
                payload["debug"] = str(message)
            
    return payload


async def _send_payload_via_alert_bot(
    chat_id: int, 
    payload: dict, 
    reply_to_message_id: int = None,
    reply_markup: InlineKeyboardMarkup = None,
    disable_notification: bool = False
) -> types.Message | None:
    """
    Sends payload via alert_bot to specified chat_id.
    Supports media buffer caching, inline buttons, silent delivery, and ReplyParameters quoting.
    Returns sent Message or None.
    """
    if alert_bot is None:
        raise RuntimeError("Alert Bot не инициализирован")

    msg_type = payload.get("type", "unsupported")
    file_id = payload.get("file_id", "")
    text = payload.get("text", "")
    caption = payload.get("caption") or None
    
    raw_entities = payload.get("entities")
    entities = None
    if raw_entities:
        from aiogram.types import MessageEntity
        entities = [MessageEntity(**e) for e in raw_entities]

    cached_id = payload.get("cached_file_id")
    media_bytes = payload.get("media_bytes")
    filename = payload.get("filename", "file")

    def _get_input_media(fallback_id):
        if cached_id:
            return cached_id
        if media_bytes:
            return BufferedInputFile(media_bytes, filename=filename)
        return fallback_id

    kwargs = {
        "reply_markup": reply_markup,
        "disable_notification": disable_notification
    }
    if reply_to_message_id:
        kwargs["reply_parameters"] = ReplyParameters(
            message_id=reply_to_message_id,
            allow_sending_without_reply=True
        )

    sent: types.Message | None = None

    if msg_type == "text":
        sent = await alert_bot.send_message(chat_id, text, entities=entities, **kwargs)
    elif msg_type == "photo":
        input_media = _get_input_media(file_id)
        sent = await alert_bot.send_photo(chat_id, input_media, caption=caption, caption_entities=entities, **kwargs)
        if sent and sent.photo and not payload.get("cached_file_id"):
            payload["cached_file_id"] = sent.photo[-1].file_id
    elif msg_type == "video":
        input_media = _get_input_media(file_id)
        sent = await alert_bot.send_video(chat_id, input_media, caption=caption, caption_entities=entities, **kwargs)
        if sent and sent.video and not payload.get("cached_file_id"):
            payload["cached_file_id"] = sent.video.file_id
    elif msg_type == "audio":
        input_media = _get_input_media(file_id)
        sent = await alert_bot.send_audio(chat_id, input_media, caption=caption, caption_entities=entities, **kwargs)
        if sent and sent.audio and not payload.get("cached_file_id"):
            payload["cached_file_id"] = sent.audio.file_id
    elif msg_type == "document":
        input_media = _get_input_media(file_id)
        sent = await alert_bot.send_document(chat_id, input_media, caption=caption, caption_entities=entities, **kwargs)
        if sent and sent.document and not payload.get("cached_file_id"):
            payload["cached_file_id"] = sent.document.file_id
    elif msg_type == "voice":
        input_media = _get_input_media(file_id)
        sent = await alert_bot.send_voice(chat_id, input_media, caption=caption, caption_entities=entities, **kwargs)
        if sent and sent.voice and not payload.get("cached_file_id"):
            payload["cached_file_id"] = sent.voice.file_id
    elif msg_type == "video_note":
        input_media = _get_input_media(file_id)
        sent = await alert_bot.send_video_note(chat_id, input_media, **kwargs)
        if sent and sent.video_note and not payload.get("cached_file_id"):
            payload["cached_file_id"] = sent.video_note.file_id
    elif msg_type == "sticker":
        sent = await alert_bot.send_sticker(chat_id, file_id, **kwargs)
    elif msg_type == "animation":
        input_media = _get_input_media(file_id)
        sent = await alert_bot.send_animation(chat_id, input_media, caption=caption, parse_mode="HTML", **kwargs)
        if sent and sent.animation and not payload.get("cached_file_id"):
            payload["cached_file_id"] = sent.animation.file_id
    else:
        raise ValueError("Данный тип сообщения (например, таблицы или спецформатирование) не поддерживается для пересылки между ботами. Пожалуйста, используйте обычный текст или медиа.")

    return sent


async def broadcast_system_alert(
    text: str,
    reply_markup: InlineKeyboardMarkup = None,
    pin: bool = False,
    disable_notification: bool = False
) -> None:
    """
    Public function to broadcast system alerts (e.g., node downtime)
    to all Gateway bot subscribers with optional buttons and pin.
    """
    if alert_bot is None:
        return
    subscribers = _load_subscribers()
    for uid in subscribers:
        s_data = subscribers.get(uid, {})
        if s_data.get("mute_all", False):
            continue
        try:
            sent = await alert_bot.send_message(
                uid,
                text,
                parse_mode="HTML",
                reply_markup=reply_markup,
                disable_notification=disable_notification
            )
            if pin and sent:
                try:
                    await alert_bot.pin_chat_message(
                        chat_id=uid,
                        message_id=sent.message_id,
                        disable_notification=True
                    )
                    try:
                        await alert_bot.delete_message(chat_id=uid, message_id=sent.message_id + 1)
                    except Exception as bubble_err:
                        logging.debug("Unable to delete system alert bubble for %s: %s", uid, bubble_err)
                except Exception as pe:
                    logging.debug(f"[client_alerts] System alert pin failed for {uid}: {pe}")
            await asyncio.sleep(0.05)
        except Exception as e:
            logging.warning(f"[client_alerts] Error sending system alert -> {uid}: {e}")


# ─── Alert Bot: Initialization ─────────────────────────────────────────────────

alert_bot: Bot | None = None
alert_dp: Dispatcher | None = None

if ALERT_BOT_TOKEN:
    try:
        alert_bot = Bot(token=ALERT_BOT_TOKEN)
        alert_dp = Dispatcher(storage=MemoryStorage())
        logging.info("[client_alerts] Alert Bot initialized successfully.")
    except Exception as _init_err:
        logging.error(f"[client_alerts] Alert Bot initialization error: {_init_err}")
        alert_bot = None
        alert_dp = None
else:
    logging.info("[client_alerts] ALERT_BOT_TOKEN not set — Alert Bot disabled.")


# ─── Inline Keyboards ────────────────────────────────────────────────────────

def _get_alert_panel_keyboard() -> InlineKeyboardMarkup:
    """
    Alert Module management panel for administrators.
    Opens when clicking "📣 Write alert" button in the main bot.
    """
    subscribers = _load_subscribers()
    history = _load_broadcast_history()
    count_label = f"({len(subscribers)} чел.)" if subscribers else "(пусто)"
    hist_label = f"({len(history)})" if history else ""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📣 Рассылка",
                    callback_data="alert_panel_broadcast",
                ),
                InlineKeyboardButton(
                    text=f"👥 Подписчики {count_label}",
                    callback_data="alert_panel_subscribers",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=f"🗑 Удалить рассылку {hist_label}".strip(),
                    callback_data="alert_panel_history",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔙 В главное меню",
                    callback_data="back_to_menu",
                ),
            ],
        ]
    )


def _get_broadcast_history_keyboard(history: list[dict]) -> InlineKeyboardMarkup:
    """Keyboard listing recent broadcasts for deletion."""
    keyboard = []
    for entry in reversed(history):
        bc_id = entry.get("id")
        date_str = entry.get("date_str", "")
        preview = entry.get("preview", "")
        btn_text = f"🗑 {date_str} — {preview[:22]}"
        keyboard.append([InlineKeyboardButton(text=btn_text, callback_data=f"alert_view_bc_{bc_id}")])
    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="alert_fsm_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def _get_broadcast_delete_confirm_keyboard(broadcast_id: str) -> InlineKeyboardMarkup:
    """Confirmation button before deleting broadcast across all subscribers."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🗑 Да, удалить у всех",
                    callback_data=f"alert_confirm_del_bc_{broadcast_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔙 Назад к списку",
                    callback_data="alert_panel_history"
                ),
            ]
        ]
    )


def _get_reply_keyboard(client_user_id: int, client_message_id: int) -> InlineKeyboardMarkup:
    """Inline 'Reply' button under incoming administrator ticket."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💬 Ответить",
                    callback_data=f"alert_reply_{client_user_id}_{client_message_id}",
                )
            ]
        ]
    )


def _render_broadcast_confirm_text(
    subscribers_count: int,
    pin: bool = False,
    silent: bool = False,
    btn_title: str | None = None,
    btn_url: str | None = None
) -> str:
    """Renders broadcast parameters summary text."""
    btn_line = f"\n🔘 Кнопка: <b>{btn_title}</b> (<code>{btn_url}</code>)" if btn_title and btn_url else "\n🔘 Кнопка: <i>не задана</i>"
    pin_line = "\n📌 Закрепить у всех: <b>Да</b>" if pin else "\n📌 Закрепить у всех: <b>Нет</b>"
    sound_line = "\n🔕 Доставка: <b>Без звука</b>" if silent else "\n🔔 Доставка: <b>Со звуком</b>"

    return (
        f"⚠️ <b>Параметры рассылки</b>\n\n"
        f"👥 Получателей: <b>{subscribers_count}</b>"
        f"{pin_line}"
        f"{sound_line}"
        f"{btn_line}\n\n"
        f"Настройте параметры ниже и нажмите <b>Отправить всем</b>:"
    )


def _get_broadcast_confirm_keyboard(
    pin: bool = False,
    silent: bool = False,
    btn_info: str | None = None
) -> InlineKeyboardMarkup:
    """Broadcast confirmation or cancellation with advanced options."""
    pin_text = "📌 Закрепить: ДА" if pin else "📌 Закрепить: НЕТ"
    sound_text = "🔕 Без звука" if silent else "🔔 Со звуком"
    btn_text = f"🔘 Кнопка: {btn_info[:14]}…" if btn_info else "🔘 Добавить кнопку"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=pin_text,
                    callback_data="alert_broadcast_toggle_pin",
                ),
                InlineKeyboardButton(
                    text=sound_text,
                    callback_data="alert_broadcast_toggle_sound",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=btn_text,
                    callback_data="alert_broadcast_setup_button",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✅ Отправить всем",
                    callback_data="alert_broadcast_confirm",
                ),
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="alert_fsm_cancel",
                ),
            ],
        ]
    )


def _get_cancel_keyboard() -> InlineKeyboardMarkup:
    """Cancel button for current FSM action."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="alert_fsm_cancel",
                )
            ]
        ]
    )


def _get_bot_lang() -> str:
    """Return the primary language of the main bot to maintain consistent localization."""
    try:
        return get_user_lang(config.ADMIN_USER_ID)
    except Exception:
        return getattr(config, "DEFAULT_LANGUAGE", "ru")


def _get_client_main_keyboard(lang: str | None = None) -> types.ReplyKeyboardMarkup:
    """Client (subscriber) keyboard with built-in settings button."""
    if not lang:
        lang = _get_bot_lang()
    return types.ReplyKeyboardMarkup(
        keyboard=[[types.KeyboardButton(text=_("alert_btn_settings", lang))]],
        resize_keyboard=True
    )


async def _get_client_settings_keyboard(user_id: int) -> InlineKeyboardMarkup:
    lang = _get_bot_lang()
    subscribers = _load_subscribers()
    s_data = subscribers.get(user_id, {})
    mute_all = s_data.get("mute_all", False)
    muted_nodes = s_data.get("muted_nodes", [])
    
    from core import nodes_db
    all_nodes = await nodes_db.get_all_nodes()
    
    keyboard = []
    mute_broadcasts = s_data.get("mute_broadcasts", False)

    if mute_all:
        mute_all_text = _("alert_btn_mute_all_on", lang)
        keyboard.append([InlineKeyboardButton(text=mute_all_text, callback_data="cst_toggle_all")])
    else:
        mute_all_text = _("alert_btn_mute_all_off", lang)
        keyboard.append([InlineKeyboardButton(text=mute_all_text, callback_data="cst_toggle_all")])
        
    if not mute_all:
        bc_text = _("alert_btn_broadcasts_off", lang) if mute_broadcasts else _("alert_btn_broadcasts_on", lang)
        keyboard.append([InlineKeyboardButton(text=bc_text, callback_data="cst_toggle_broadcasts")])

        for token, n_data in all_nodes.items():
            name = n_data.get("name", "Unknown")
            is_muted = token in muted_nodes
            btn_text = f"🔕 {name}" if is_muted else f"🔔 {name}"
            keyboard.append([InlineKeyboardButton(text=btn_text, callback_data=f"cst_node_{token}")])
            
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# ─── Alert Bot: Handlers ───────────────────────────────────────────────────

if alert_dp is not None:

    @alert_dp.message(Command("start"))
    async def alert_start_handler(message: types.Message) -> None:
        """
        Client clicks /start in Alert Bot → subscribes to broadcast alerts.
        """
        user_id = message.from_user.id
        lang = _get_bot_lang()
        user_name = message.from_user.full_name or f"ID {user_id}"
        is_new = await _add_subscriber(user_id, user_name)

        if is_new:
            await message.answer(
                _("alert_welcome_new", lang),
                parse_mode="HTML",
                reply_markup=_get_client_main_keyboard(lang)
            )
            logging.info(f"[client_alerts] New subscriber: {user_id} ({user_name})")
        else:
            await message.answer(
                _("alert_welcome_existing", lang),
                parse_mode="HTML",
                reply_markup=_get_client_main_keyboard(lang)
            )

    @alert_dp.callback_query(F.data == "cst_toggle_all")
    async def _cq_client_settings_toggle_all(callback: types.CallbackQuery):
        user_id = callback.from_user.id
        subscribers = _load_subscribers()
        s_data = subscribers.get(user_id, {})
        mute_all = s_data.get("mute_all", False)
        lang = _get_bot_lang()

        if not mute_all:
            # User intends to mute all -> send humorous warning with OK and Cancel buttons first
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=_("alert_btn_confirm_mute", lang),
                            callback_data="cst_confirm_mute_all"
                        ),
                        InlineKeyboardButton(
                            text=_("alert_btn_cancel_mute", lang),
                            callback_data="cst_cancel_mute_all"
                        ),
                    ]
                ]
            )
            warn_text = _("alert_mute_all_warning", lang)
            try:
                await callback.message.edit_text(warn_text, parse_mode="HTML", reply_markup=kb)
            except Exception as exc:
                logging.debug("Unable to edit message to show mute warning: %s", exc)
                try:
                    await callback.message.answer(warn_text, parse_mode="HTML", reply_markup=kb)
                except Exception as exc2:
                    logging.debug("Unable to send mute warning message: %s", exc2)
            await callback.answer()
            return

        # If currently muted, clicking toggles it back to unmuted immediately
        if user_id in subscribers:
            subscribers[user_id]["mute_all"] = False
            _save_subscribers(subscribers)
            try:
                await callback.message.edit_reply_markup(reply_markup=await _get_client_settings_keyboard(user_id))
            except Exception as exc:
                logging.debug("Unable to refresh client alert settings keyboard: %s", exc)
        await callback.answer(_("alert_unmuted_all_notify", lang))

    @alert_dp.callback_query(F.data == "cst_confirm_mute_all")
    async def _cq_client_confirm_mute_all(callback: types.CallbackQuery):
        user_id = callback.from_user.id
        subscribers = _load_subscribers()
        lang = _get_bot_lang()
        if user_id in subscribers:
            subscribers[user_id]["mute_all"] = True
            _save_subscribers(subscribers)
        try:
            await callback.message.edit_text(
                _("alert_settings_text", lang),
                parse_mode="HTML",
                reply_markup=await _get_client_settings_keyboard(user_id)
            )
        except Exception as exc:
            logging.debug("Unable to restore settings keyboard after confirm mute: %s", exc)
        await callback.answer(_("alert_mute_all_confirmed", lang))

    @alert_dp.callback_query(F.data == "cst_cancel_mute_all")
    async def _cq_client_cancel_mute_all(callback: types.CallbackQuery):
        user_id = callback.from_user.id
        lang = _get_bot_lang()
        try:
            await callback.message.edit_text(
                _("alert_settings_text", lang),
                parse_mode="HTML",
                reply_markup=await _get_client_settings_keyboard(user_id)
            )
        except Exception as exc:
            logging.debug("Unable to restore settings keyboard after cancel mute: %s", exc)
        await callback.answer(_("alert_mute_all_cancelled", lang))

    @alert_dp.callback_query(F.data == "cst_toggle_broadcasts")
    async def _cq_client_settings_toggle_broadcasts(callback: types.CallbackQuery):
        user_id = callback.from_user.id
        subscribers = _load_subscribers()
        if user_id in subscribers:
            subscribers[user_id]["mute_broadcasts"] = not subscribers[user_id].get("mute_broadcasts", False)
            _save_subscribers(subscribers)
            try:
                await callback.message.edit_reply_markup(reply_markup=await _get_client_settings_keyboard(user_id))
            except Exception as exc:
                logging.debug("Unable to refresh client alert settings keyboard: %s", exc)
        await callback.answer()

    @alert_dp.callback_query(F.data.startswith("cst_node_"))
    async def _cq_client_settings_toggle_node(callback: types.CallbackQuery):
        user_id = callback.from_user.id
        token = callback.data.replace("cst_node_", "")
        subscribers = _load_subscribers()
        if user_id in subscribers:
            muted_nodes = subscribers[user_id].setdefault("muted_nodes", [])
            if token in muted_nodes:
                muted_nodes.remove(token)
            else:
                muted_nodes.append(token)
            _save_subscribers(subscribers)
            try:
                await callback.message.edit_reply_markup(reply_markup=await _get_client_settings_keyboard(user_id))
            except Exception as exc:
                logging.debug("Unable to refresh client alert settings keyboard: %s", exc)
        await callback.answer()

    @alert_dp.message()
    async def alert_message_handler(message: types.Message) -> None:
        """
        Any client message in Alert Bot → forwarded to administrator via main bot.
        Administrator sees message with inline 'Reply' button.
        """
        if alert_bot is None:
            return

        # Ignore and delete Telegram service event for pinned messages
        if getattr(message, "pinned_message", None) is not None:
            try:
                await message.delete()
            except Exception as exc:
                logging.debug("Unable to delete pinned service message: %s", exc)
            return

        # Ignore messages from bots
        if message.from_user and message.from_user.is_bot:
            return

        # Ignore any service events that are not user content
        is_user_content = any([
            message.text,
            message.caption,
            message.photo,
            message.video,
            message.audio,
            message.document,
            message.voice,
            message.video_note,
            message.sticker,
            message.animation,
        ])
        if not is_user_content:
            return

        lang = _get_bot_lang()
        if message.text in ["⚙️ Настройки", "⚙️ Settings", _("alert_btn_settings", "ru"), _("alert_btn_settings", "en"), "/settings"]:
            user_id = message.from_user.id
            user_name = message.from_user.full_name or f"ID {user_id}"
            await _add_subscriber(user_id, user_name)
            
            text = _("alert_settings_text", lang)
            await message.answer(text, parse_mode="HTML", reply_markup=await _get_client_settings_keyboard(user_id))
            return

        # Check that this is a reply to a message
        if not message.reply_to_message:
            await message.answer(_("alert_reply_error_not_reply", lang), parse_mode="HTML")
            return

        reply = message.reply_to_message
        
        # Check for replying to oneself (BUG 5)
        if reply.from_user.id == message.from_user.id:
             await message.answer(_("alert_reply_error_self", lang))
             return

        # Check for replying to bot's system message (BUG 6)
        if reply.from_user.id == alert_bot.id:
            if reply.text and (reply.text.startswith("⚠️") or reply.text.startswith("✅") or reply.text.startswith("👋") or reply.text.startswith("⏳")):
                 await message.answer(_("alert_reply_error_bot", lang))
                 return

        # Ensure user is subscribed
        user_id = message.from_user.id
        user_name = message.from_user.full_name or f"ID {user_id}"
        await _add_subscriber(user_id, user_name)

        # Anti-flood: max 1 message per 3 seconds
        now = time.time()
        global _last_flood_state_cleanup
        if now - _last_flood_state_cleanup >= 60 or len(_user_last_message_time) >= _MAX_USER_FLOOD_STATES:
            stale = [uid for uid, timestamp in _user_last_message_time.items() if now - timestamp > _USER_FLOOD_STATE_TTL]
            for uid in stale:
                _user_last_message_time.pop(uid, None)
            overflow = len(_user_last_message_time) - _MAX_USER_FLOOD_STATES
            if overflow > 0:
                oldest = sorted(_user_last_message_time, key=_user_last_message_time.get)[:overflow]
                for uid in oldest:
                    _user_last_message_time.pop(uid, None)
            _last_flood_state_cleanup = now
        last_time = _user_last_message_time.get(user_id, 0)
        if now - last_time < 3.0:
            await message.answer(_("alert_flood_wait", lang))
            return
        _user_last_message_time[user_id] = now

        user_name = message.from_user.full_name or f"ID {user_id}"
        username_str = (
            f"@{message.from_user.username}"
            if message.from_user.username
            else "нет username"
        )

        ticket_header = (
            f"📨 <b>Вам ответили на алерт</b>\n"
            f"👤 <b>{user_name}</b> ({username_str})\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        )

        # Lazy import of the main bot to avoid circular imports
        try:
            import bot as main_bot_module
            main_bot_instance: Bot = main_bot_module.bot
        except ImportError:
            logging.error("[client_alerts] Failed to import the main bot.")
            return

        try:
            await main_bot_instance.send_message(
                config.ADMIN_USER_ID,
                ticket_header,
                parse_mode="HTML",
                reply_markup=_get_reply_keyboard(user_id, message.message_id),
            )
            if message.text:
                await main_bot_instance.send_message(
                    config.ADMIN_USER_ID,
                    f"<i>{message.text}</i>",
                    parse_mode="HTML",
                )
            else:
                # Media — forward original
                await message.forward(config.ADMIN_USER_ID)

            await message.answer(_("alert_msg_sent", lang))

        except Exception as e:
            logging.error(f"[client_alerts] Error forwarding ticket: {e}")
            await message.answer("⚠️ Error / Ошибка при отправке. Попробуйте позже.")


# ─── Main Bot: Control Panel (callback) ───────────────────────────────────

async def _alert_panel_open(message: types.Message, state: FSMContext) -> None:
    """
    Button '📣 Write alert' clicked in main bot → show control panel.
    Available only to admin; regular users receive informational message.
    """
    user_id = message.from_user.id

    if user_id != config.ADMIN_USER_ID:
        # To regular users — info message instead of error
        await message.answer(
            "📣 <b>Alert Bot</b>\n\n"
            "Этот раздел предназначен для отправки обращений администратору.\n"
            "Ваши обращения можно направлять напрямую нашему боту.",
            parse_mode="HTML",
        )
        return

    await state.clear()
    subscribers = _load_subscribers()
    text = (
        f"📣 <b>Alert Module — Панель управления</b>\n\n"
        f"👥 Подписчиков: <b>{len(subscribers)}</b>\n"
        f"🤖 Alert Bot: <b>{'активен' if alert_bot else 'не активен'}</b>\n\n"
        f"Выберите действие:"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=_get_alert_panel_keyboard())


async def _cq_panel_broadcast(callback: types.CallbackQuery, state: FSMContext) -> None:
    """
    Button '📣 Broadcast' in panel → switch to FSM waiting for broadcast message.
    """
    if callback.from_user.id != config.ADMIN_USER_ID:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return

    subscribers = _load_subscribers()
    if not subscribers:
        await callback.answer("📭 Нет подписчиков для рассылки.", show_alert=True)
        return

    await state.set_state(BroadcastStates.waiting_broadcast_message)
    await state.update_data(panel_message_id=callback.message.message_id)
    await callback.answer()
    
    text = (
        f"📣 <b>Рассылка</b>\n\n"
        f"Подписчиков: <b>{len(subscribers)}</b>\n\n"
        f"Отправьте сообщение для рассылки (текст, фото, видео и т.д.):"
    )
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=_get_cancel_keyboard())
    except Exception as exc:
        logging.debug("Unable to display broadcast prompt: %s", exc)


async def _cq_panel_subscribers(callback: types.CallbackQuery) -> None:
    """
    Button '👥 Subscribers' → display subscribers list directly in inline message.
    """
    if callback.from_user.id != config.ADMIN_USER_ID:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return

    page = 1
    if callback.data.startswith("alert_panel_subscribers_page_"):
        page = int(callback.data.split("_")[-1])

    subscribers = _load_subscribers()
    await callback.answer()

    if not subscribers:
        text = (
            "📣 <b>Alert Module — Панель управления</b>\n\n"
            "📭 Подписчиков пока нет.\n\n"
            "Выберите действие:"
        )
        markup = _get_alert_panel_keyboard()
    else:
        PER_PAGE = 5
        items = list(subscribers.items())
        total_pages = max(1, (len(items) + PER_PAGE - 1) // PER_PAGE)
        page = min(page, total_pages)
        page = max(page, 1)
            
        start_idx = (page - 1) * PER_PAGE
        end_idx = start_idx + PER_PAGE
        current_items = items[start_idx:end_idx]
        
        if alert_bot is not None:
            updated = False
            for idx, (uid, s_data) in enumerate(current_items):
                name = s_data.get("name", "")
                if name.startswith("ID "):
                    try:
                        chat = await alert_bot.get_chat(uid)
                        new_name = chat.full_name or f"ID {uid}"
                        if new_name != name:
                            subscribers[uid]["name"] = new_name
                            current_items[idx] = (uid, subscribers[uid])
                            updated = True
                    except Exception as exc:
                        logging.debug("Unable to refresh subscriber profile: %s", exc)
            if updated:
                _save_subscribers(subscribers)
        
        ids_text = "\n".join(f"  • {s_data.get('name', 'Unknown')} (<code>{uid}</code>)" for uid, s_data in current_items)
        
        text = (
            f"📣 <b>Alert Module — Подписчики</b>\n\n"
            f"👥 Всего: <b>{len(subscribers)}</b>\n"
            f"📄 Страница {page} из {total_pages}\n\n"
            f"{ids_text}\n"
        )
        
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"alert_panel_subscribers_page_{page - 1}"))
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"alert_panel_subscribers_page_{page + 1}"))
            
        keyboard = []
        if nav_buttons:
            keyboard.append(nav_buttons)
        keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="alert_fsm_cancel")])
        markup = InlineKeyboardMarkup(inline_keyboard=keyboard)

    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    except Exception as exc:
        logging.debug("Unable to refresh subscribers menu: %s", exc)


# ─── Main Bot: FSM — Broadcast ─────────────────────────────────────────────────

async def _broadcast_message_received(
    message: types.Message, state: FSMContext
) -> None:
    """
    Received message for broadcast → save payload in FSM state and request confirmation.
    """
    payload = await _extract_message_payload(message)
    subscribers = _load_subscribers()
    
    data = await state.get_data()
    panel_message_id = data.get("panel_message_id")
    await state.update_data(
        broadcast_payload=payload,
        broadcast_pin=False,
        broadcast_silent=False,
        btn_title=None,
        btn_url=None
    )
    
    text = _render_broadcast_confirm_text(len(subscribers), pin=False, silent=False, btn_title=None, btn_url=None)
    markup = _get_broadcast_confirm_keyboard(pin=False, silent=False, btn_info=None)

    try:
        await message.delete()
    except Exception as exc:
        logging.debug("Unable to delete broadcast input message: %s", exc)

    try:
        import bot as main_bot_module
        main_bot_instance: Bot = main_bot_module.bot
        await main_bot_instance.edit_message_text(
            chat_id=message.chat.id,
            message_id=panel_message_id,
            text=text,
            parse_mode="HTML",
            reply_markup=markup,
        )
    except Exception:
        await message.answer(text, parse_mode="HTML", reply_markup=markup)


async def _cq_broadcast_toggle_pin(callback: types.CallbackQuery, state: FSMContext) -> None:
    """Toggle message pinning for broadcast."""
    if callback.from_user.id != config.ADMIN_USER_ID:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    data = await state.get_data()
    cur_pin = not data.get("broadcast_pin", False)
    await state.update_data(broadcast_pin=cur_pin)
    
    subscribers = _load_subscribers()
    silent = data.get("broadcast_silent", False)
    btn_title = data.get("btn_title")
    btn_url = data.get("btn_url")
    
    text = _render_broadcast_confirm_text(len(subscribers), cur_pin, silent, btn_title, btn_url)
    markup = _get_broadcast_confirm_keyboard(pin=cur_pin, silent=silent, btn_info=btn_title)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    except Exception as exc:
        logging.debug("Unable to update broadcast pin setting: %s", exc)
    await callback.answer()


async def _cq_broadcast_toggle_sound(callback: types.CallbackQuery, state: FSMContext) -> None:
    """Toggle silent delivery for broadcast."""
    if callback.from_user.id != config.ADMIN_USER_ID:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    data = await state.get_data()
    cur_silent = not data.get("broadcast_silent", False)
    await state.update_data(broadcast_silent=cur_silent)
    
    subscribers = _load_subscribers()
    pin = data.get("broadcast_pin", False)
    btn_title = data.get("btn_title")
    btn_url = data.get("btn_url")
    
    text = _render_broadcast_confirm_text(len(subscribers), pin, cur_silent, btn_title, btn_url)
    markup = _get_broadcast_confirm_keyboard(pin=pin, silent=cur_silent, btn_info=btn_title)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    except Exception as exc:
        logging.debug("Unable to update broadcast sound setting: %s", exc)
    await callback.answer()


async def _cq_broadcast_setup_button(callback: types.CallbackQuery, state: FSMContext) -> None:
    """Ask administrator for custom inline button title and URL."""
    if callback.from_user.id != config.ADMIN_USER_ID:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    await state.set_state(BroadcastStates.waiting_broadcast_button)
    await callback.answer()
    
    text = (
        "🔘 <b>Настройка кнопки для рассылки</b>\n\n"
        "Отправьте текст кнопки и ссылку через разделитель <code>|</code>:\n"
        "<code>Пример: Наш канал | https://t.me/telegram</code>\n\n"
        "Или отправьте <code>-</code> (дефис), чтобы удалить кнопку."
    )
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=_get_cancel_keyboard())
    except Exception as exc:
        logging.debug("Unable to display setup button prompt: %s", exc)


async def _broadcast_button_received(message: types.Message, state: FSMContext) -> None:
    """Handles administrator input for broadcast inline button."""
    data = await state.get_data()
    panel_message_id = data.get("panel_message_id")
    raw_text = (message.text or "").strip()
    
    try:
        await message.delete()
    except Exception as exc:
        logging.debug("Unable to delete broadcast button input message: %s", exc)

    if raw_text in ["-", "—", "удалить", "убрать", "del", "none"]:
        await state.update_data(btn_title=None, btn_url=None)
    elif "|" in raw_text:
        parts = raw_text.split("|", 1)
        title = parts[0].strip()
        url = parts[1].strip()
        if (url.startswith("http://") or url.startswith("https://") or url.startswith("tg://")) and title:
            await state.update_data(btn_title=title, btn_url=url)
        else:
            await message.answer(
                "⚠️ Некорректная ссылка! Ссылка должна начинаться с <code>http://</code>, <code>https://</code> или <code>tg://</code>",
                parse_mode="HTML"
            )
            return
    else:
        await message.answer(
            "⚠️ Формат: <code>Текст кнопки | https://ссылка</code> или <code>-</code> чтобы убрать.",
            parse_mode="HTML"
        )
        return

    await state.set_state(BroadcastStates.waiting_broadcast_message)
    subscribers = _load_subscribers()
    updated_data = await state.get_data()
    pin = updated_data.get("broadcast_pin", False)
    silent = updated_data.get("broadcast_silent", False)
    btn_title = updated_data.get("btn_title")
    btn_url = updated_data.get("btn_url")
    
    text = _render_broadcast_confirm_text(len(subscribers), pin, silent, btn_title, btn_url)
    markup = _get_broadcast_confirm_keyboard(pin=pin, silent=silent, btn_info=btn_title)
    
    import bot as main_bot_module
    main_bot_instance: Bot = main_bot_module.bot
    try:
        await main_bot_instance.edit_message_text(
            chat_id=message.chat.id,
            message_id=panel_message_id,
            text=text,
            parse_mode="HTML",
            reply_markup=markup,
        )
    except Exception:
        await message.answer(text, parse_mode="HTML", reply_markup=markup)


async def _broadcast_confirm(
    callback: types.CallbackQuery, state: FSMContext
) -> None:
    """Administrator confirmed broadcast."""
    if callback.from_user.id != config.ADMIN_USER_ID:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return

    data = await state.get_data()
    payload = data.get("broadcast_payload")
    pin = data.get("broadcast_pin", False)
    silent = data.get("broadcast_silent", False)
    btn_title = data.get("btn_title")
    btn_url = data.get("btn_url")
    await state.clear()

    if not payload:
        await callback.answer("⚠️ Данные рассылки утеряны.", show_alert=True)
        return

    if alert_bot is None:
        await callback.answer("⚠️ Alert Bot не активен.", show_alert=True)
        return

    subscribers = _load_subscribers()
    if not subscribers:
        await callback.answer("📭 Нет подписчиков.", show_alert=True)
        return

    await callback.answer("📤 Рассылка запущена...")
    try:
        await callback.message.edit_text("⏳ <b>Рассылка запущена...</b>\nПожалуйста, подождите.", parse_mode="HTML", reply_markup=None)
    except Exception as exc:
        logging.debug("Unable to display broadcast progress: %s", exc)

    custom_kb = None
    if btn_title and btn_url:
        custom_kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=btn_title, url=btn_url)]]
        )

    sent_ok = 0
    sent_fail = 0
    sent_messages: dict[int, int] = {}

    for uid in subscribers:
        s_data = subscribers.get(uid, {})
        if s_data.get("mute_all", False) or s_data.get("mute_broadcasts", False):
            continue
        try:
            sent = await _send_payload_via_alert_bot(
                uid,
                payload,
                reply_markup=custom_kb,
                disable_notification=silent
            )
            if sent:
                sent_messages[uid] = sent.message_id
                if pin and alert_bot:
                    try:
                        await alert_bot.pin_chat_message(
                            chat_id=uid,
                            message_id=sent.message_id,
                            disable_notification=True
                        )
                        # Delete Telegram pin service bubble (sent.message_id + 1) to leave no trace in chat
                        try:
                            await alert_bot.delete_message(chat_id=uid, message_id=sent.message_id + 1)
                        except Exception as bubble_err:
                            logging.debug("Unable to delete broadcast service bubble for %s: %s", uid, bubble_err)
                    except Exception as pe:
                        logging.debug(f"[client_alerts] Pin failed for {uid}: {pe}")
            sent_ok += 1
            await asyncio.sleep(0.05)  # rate limit guard
        except Exception as e:
            logging.warning(f"[client_alerts] Broadcast → {uid}: {e}")
            sent_fail += 1

    bc_id = None
    if sent_messages:
        preview_text = payload.get("text") or payload.get("caption") or f"Медиа ({payload.get('type')})"
        bc_id = _record_broadcast(preview_text, sent_messages, is_pinned=bool(pin))

    result_text = (
        f"✅ <b>Рассылка завершена</b>\n\n"
        f"📤 Успешно: <b>{sent_ok}</b>\n"
        f"❌ Ошибок: <b>{sent_fail}</b>\n\n"
        f"Выберите действие:"
    )

    if bc_id:
        result_markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🗑 Отозвать (удалить у всех)",
                        callback_data=f"alert_confirm_del_bc_{bc_id}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔙 В панель управления",
                        callback_data="alert_panel_open_again"
                    ),
                    InlineKeyboardButton(
                        text="🚪 В главное меню",
                        callback_data="back_to_menu"
                    ),
                ]
            ]
        )
    else:
        result_markup = _get_alert_panel_keyboard()

    try:
        await callback.message.edit_text(result_text, parse_mode="HTML", reply_markup=result_markup)
    except Exception as exc:
        logging.debug("Unable to display broadcast result: %s", exc)


async def _cq_panel_open_again(callback: types.CallbackQuery, state: FSMContext) -> None:
    """Return to alert panel menu."""
    if callback.from_user.id != config.ADMIN_USER_ID:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return
    await state.clear()
    subscribers = _load_subscribers()
    text = (
        f"📣 <b>Alert Module — Панель управления</b>\n\n"
        f"👥 Подписчиков: <b>{len(subscribers)}</b>\n"
        f"🤖 Alert Bot: <b>{'активен' if alert_bot else 'не активен'}</b>\n\n"
        f"Выберите действие:"
    )
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=_get_alert_panel_keyboard())
    except Exception as exc:
        logging.debug("Unable to return to alert panel: %s", exc)
    await callback.answer()


async def _cq_panel_history(callback: types.CallbackQuery) -> None:
    """Display list of recent broadcasts available for deletion."""
    if callback.from_user.id != config.ADMIN_USER_ID:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return

    history = _load_broadcast_history()
    if not history:
        await callback.answer("📭 История рассылок пуста (нет активных сообщений).", show_alert=True)
        return

    await callback.answer()
    text = (
        f"🗑 <b>Удаление сообщений у клиентов</b>\n\n"
        f"Выберите рассылку, которую требуется удалить из личных сообщений у всех подписчиков:\n"
    )
    markup = _get_broadcast_history_keyboard(history)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    except Exception as exc:
        logging.debug("Unable to display broadcast history: %s", exc)


async def _cq_view_broadcast(callback: types.CallbackQuery) -> None:
    """Show details of selected broadcast and ask for deletion confirmation."""
    if callback.from_user.id != config.ADMIN_USER_ID:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return

    bc_id = callback.data.replace("alert_view_bc_", "")
    history = _load_broadcast_history()
    target = next((item for item in history if item.get("id") == bc_id), None)

    if not target:
        await callback.answer("⚠️ Рассылка не найдена или уже удалена.", show_alert=True)
        return

    await callback.answer()
    recipients_count = len(target.get("sent", {}))
    text = (
        f"🗑 <b>Удаление рассылки у клиентов</b>\n\n"
        f"📅 Дата: <b>{target.get('date_str', 'Неизвестно')}</b>\n"
        f"💬 Текст/медиа: <i>{target.get('preview', 'Без текста')}</i>\n"
        f"👥 Получателей: <b>{recipients_count}</b>\n\n"
        f"⚠️ Это сообщение будет безвозвратно удалено у всех {recipients_count} подписчиков. Продолжить?"
    )
    markup = _get_broadcast_delete_confirm_keyboard(bc_id)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    except Exception as exc:
        logging.debug("Unable to display delete confirmation: %s", exc)


async def _cq_confirm_delete_broadcast(callback: types.CallbackQuery) -> None:
    """Execute broadcast message deletion across all subscribers."""
    if callback.from_user.id != config.ADMIN_USER_ID:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return

    bc_id = callback.data.replace("alert_confirm_del_bc_", "")
    await callback.answer("🗑 Удаляю сообщения у всех клиентов...")
    try:
        await callback.message.edit_text(
            "⏳ <b>Удаление сообщений у всех подписчиков...</b>\nПожалуйста, подождите.",
            parse_mode="HTML"
        )
    except Exception as exc:
        logging.debug("Unable to display deletion progress: %s", exc)

    del_ok, del_fail = await _delete_broadcast_for_all(bc_id)

    result_text = (
        f"✅ <b>Рассылка удалена у клиентов</b>\n\n"
        f"🗑 Удалено сообщений: <b>{del_ok}</b>\n"
        f"⚠️ Не удалось (уже удалено пользователем): <b>{del_fail}</b>\n\n"
        f"Выберите действие:"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔙 В панель управления", callback_data="alert_panel_open_again"),
                InlineKeyboardButton(text="🚪 В главное меню", callback_data="back_to_menu"),
            ]
        ]
    )
    try:
        await callback.message.edit_text(result_text, parse_mode="HTML", reply_markup=kb)
    except Exception as exc:
        logging.debug("Unable to display deletion result: %s", exc)


# ─── Main Bot: FSM — Ticket Reply ──────────────────────────────────────────

async def _alert_reply_callback(
    callback: types.CallbackQuery, state: FSMContext
) -> None:
    """
    Button '💬 Reply' under incoming ticket → switch to FSM ReplyStates.
    """
    if callback.from_user.id != config.ADMIN_USER_ID:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return

    try:
        parts = callback.data.split("_")
        client_user_id = int(parts[2])
        client_message_id = int(parts[3])
    except (IndexError, ValueError):
        await callback.answer("⚠️ Некорректный ID клиента или сообщения.", show_alert=True)
        return

    await state.set_state(ReplyStates.waiting_reply_text)
    await state.update_data(reply_to_user_id=client_user_id, reply_to_message_id=client_message_id, panel_message_id=callback.message.message_id)

    await callback.answer()
    
    text = (
        f"✏️ <b>Ответ клиенту</b> <code>{client_user_id}</code>\n\n"
        f"Отправьте ваш ответ (текст, фото, голосовое и т.д.):"
    )
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=_get_cancel_keyboard())
    except Exception as exc:
        logging.debug("Unable to display alert reply prompt: %s", exc)


async def _reply_text_received(message: types.Message, state: FSMContext) -> None:
    """
    Received administrator reply → forward to client via alert_bot
    using file_id / text directly.
    """
    data = await state.get_data()
    client_user_id = data.get("reply_to_user_id")
    client_message_id = data.get("reply_to_message_id")
    panel_message_id = data.get("panel_message_id")
    await state.clear()

    if not client_user_id:
        await message.answer("⚠️ Ошибка: ID клиента не найден.")
        return

    if alert_bot is None:
        await message.answer("⚠️ Alert Bot не активен — ответ невозможен.")
        return

    payload = await _extract_message_payload(message)
    
    try:
        await message.delete()
    except Exception as exc:
        logging.debug("Unable to delete alert reply input message: %s", exc)

    try:
        await _send_payload_via_alert_bot(client_user_id, payload, reply_to_message_id=client_message_id)
        logging.info(f"[client_alerts] Reply sent to client {client_user_id}.")
        text = f"✅ <b>Ответ отправлен</b> клиенту <code>{client_user_id}</code>."
    except Exception as e:
        logging.error(f"[client_alerts] Error replying to client {client_user_id}: {e}")
        text = f"❌ Ошибка отправки <code>{client_user_id}</code>: {e}"

    try:
        import bot as main_bot_module
        main_bot_instance: Bot = main_bot_module.bot
        await main_bot_instance.edit_message_text(
            chat_id=message.chat.id,
            message_id=panel_message_id,
            text=text + "\n\nВыберите действие:",
            parse_mode="HTML",
            reply_markup=_get_alert_panel_keyboard()
        )
    except Exception:
        await message.answer(text, parse_mode="HTML", reply_markup=_get_alert_panel_keyboard())


# ─── Main Bot: General FSM cancellation via button ─────────────────────────────────

async def _cq_fsm_cancel(callback: types.CallbackQuery, state: FSMContext) -> None:
    """
    Button '❌ Cancel' during any FSM input (broadcast, reply).
    If in button input mode, returns to broadcast preview.
    Otherwise resets state and returns to control panel.
    """
    current_state = await state.get_state()
    if current_state == BroadcastStates.waiting_broadcast_button.state:
        await state.set_state(BroadcastStates.waiting_broadcast_message)
        data = await state.get_data()
        pin = data.get("broadcast_pin", False)
        silent = data.get("broadcast_silent", False)
        btn_title = data.get("btn_title")
        btn_url = data.get("btn_url")
        subscribers = _load_subscribers()
        text = _render_broadcast_confirm_text(len(subscribers), pin, silent, btn_title, btn_url)
        markup = _get_broadcast_confirm_keyboard(pin=pin, silent=silent, btn_info=btn_title)
        try:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
        except Exception as exc:
            logging.debug("Unable to restore broadcast menu: %s", exc)
        await callback.answer("Ввод кнопки отменен.")
        return

    await state.clear()
    subscribers = _load_subscribers()
    text = (
        f"📣 <b>Alert Module — Панель управления</b>\n\n"
        f"👥 Подписчиков: <b>{len(subscribers)}</b>\n"
        f"🤖 Alert Bot: <b>{'активен' if alert_bot else 'не активен'}</b>\n\n"
        f"Выберите действие:"
    )
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=_get_alert_panel_keyboard())
    except Exception as exc:
        logging.debug("Unable to display cancelled alert menu: %s", exc)
    await callback.answer("Отменено.")


# ─── register_handlers + start_background_tasks ───────────────────────────────

def register_handlers(dp: Dispatcher) -> None:
    """
    Registers handlers in the MAIN bot.
    Called by orchestrator when module is loaded (tier=ALWAYS_ON).
    """
    if not ALERT_BOT_TOKEN:
        logging.info(
            "[client_alerts] ALERT_BOT_TOKEN not set. "
            "Alert Module handlers not registered."
        )
        return

    # Button «📣 Write alert» -> control panel
    dp.message(I18nFilter("btn_client_alerts"))(_alert_panel_open)

    # Callback: «📣 Broadcast» in panel
    dp.callback_query(F.data == "alert_panel_broadcast")(_cq_panel_broadcast)

    # Callback: «👥 Subscribers» in panel
    dp.callback_query(F.data == "alert_panel_subscribers")(_cq_panel_subscribers)
    dp.callback_query(F.data.startswith("alert_panel_subscribers_page_"))(_cq_panel_subscribers)

    # FSM: received message for broadcast
    dp.message(BroadcastStates.waiting_broadcast_message)(_broadcast_message_received)

    # Broadcast advanced callbacks & inputs
    dp.callback_query(F.data == "alert_broadcast_toggle_pin")(_cq_broadcast_toggle_pin)
    dp.callback_query(F.data == "alert_broadcast_toggle_sound")(_cq_broadcast_toggle_sound)
    dp.callback_query(F.data == "alert_broadcast_setup_button")(_cq_broadcast_setup_button)
    dp.message(BroadcastStates.waiting_broadcast_button)(_broadcast_button_received)

    # Broadcast confirmation callbacks
    dp.callback_query(F.data == "alert_broadcast_confirm")(_broadcast_confirm)

    # Broadcast history & deletion callbacks
    dp.callback_query(F.data == "alert_panel_history")(_cq_panel_history)
    dp.callback_query(F.data == "alert_panel_open_again")(_cq_panel_open_again)
    dp.callback_query(F.data.startswith("alert_view_bc_"))(_cq_view_broadcast)
    dp.callback_query(F.data.startswith("alert_confirm_del_bc_"))(_cq_confirm_delete_broadcast)

    # Callback «💬 Reply» under incoming ticket
    dp.callback_query(F.data.startswith("alert_reply_"))(_alert_reply_callback)

    # FSM: received administrator reply message
    dp.message(ReplyStates.waiting_reply_text)(_reply_text_received)

    # Button «❌ Cancel» in any FSM mode
    dp.callback_query(F.data == "alert_fsm_cancel")(_cq_fsm_cancel)

    logging.info(
        "[client_alerts] Alert Module handlers registered on the main bot."
    )


def start_background_tasks(bot: Bot) -> list[asyncio.Task]:
    """
    Starts Alert Bot polling as a background asyncio task.
    Called by orchestrator for ALWAYS_ON modules.

    Args:
        bot: MAIN bot instance (signature required by orchestrator).

    Returns:
        List of asyncio.Task. Empty if ALERT_BOT_TOKEN is not set.
    """
    if alert_bot is None or alert_dp is None:
        logging.info("[client_alerts] Alert Bot not started (token not set).")
        return []

    async def _run_alert_polling() -> None:
        """Starts Alert Bot polling with graceful shutdown."""
        logging.info(log_text("client_alerts_polling_start"))
        try:
            await alert_bot.delete_webhook(drop_pending_updates=True)
            # handle_signals=False: the main bot owns the single process-wide SIGINT/SIGTERM
            # handler (see bot.py); a second dispatcher registering its own would silently
            # steal the signal and prevent the main bot from shutting down gracefully.
            await alert_dp.start_polling(
                alert_bot,
                allowed_updates=alert_dp.resolve_used_update_types(),
                handle_signals=False,
            )
        except asyncio.CancelledError:
            logging.info("[client_alerts] Alert Bot polling stopped.")
        except Exception as e:
            logging.error(f"[client_alerts] Critical Alert Bot error: {e}", exc_info=True)
        finally:
            try:
                session = getattr(alert_bot, "session", None)
                if session:
                    await session.close()
            except Exception as exc:
                logging.debug("Unable to close alert bot session: %s", exc)
            logging.info("[client_alerts] Alert Bot finished.")

    task = asyncio.create_task(_run_alert_polling(), name="AlertBotPolling")
    logging.info("[client_alerts] Alert Bot background task created.")
    return [task]
