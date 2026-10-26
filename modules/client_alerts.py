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
import html
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


def _get_client_lang(user_id: int, tg_lang: str | None = None) -> str:
    """Get subscriber's preferred language, falling back to Telegram language code or bot language."""
    subscribers = _load_subscribers()
    s_data = subscribers.get(user_id, {})
    if s_data.get("lang"):
        return s_data["lang"]
    if tg_lang:
        code = str(tg_lang).lower()
        if code.startswith(("ru", "be", "uk")):
            return "ru"
        return "en"
    return _get_bot_lang()


async def _add_subscriber(user_id: int, user_name: str, tg_lang: str | None = None) -> bool:
    """Add a subscriber or update name and language. Returns True if added for the first time."""
    subscribers = _load_subscribers()
    is_new = user_id not in subscribers
    if is_new:
        lang = "ru" if (tg_lang and str(tg_lang).lower().startswith(("ru", "be", "uk"))) else ("en" if tg_lang else _get_bot_lang())
        subscribers[user_id] = {
            "name": user_name,
            "mute_all": False,
            "mute_broadcasts": False,
            "muted_nodes": [],
            "lang": lang,
        }
        _save_subscribers(subscribers)
    else:
        changed = False
        if subscribers[user_id].get("name") != user_name:
            subscribers[user_id]["name"] = user_name
            changed = True
        if "lang" not in subscribers[user_id] and tg_lang:
            subscribers[user_id]["lang"] = "ru" if str(tg_lang).lower().startswith(("ru", "be", "uk")) else "en"
            changed = True
        if changed:
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
POLLS_FILE = os.path.join(config.CONFIG_DIR, "alert_polls.json")


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


def _load_polls_registry() -> dict[str, dict]:
    """Loads polls registry mapping poll_id -> metadata."""
    try:
        if os.path.exists(POLLS_FILE):
            with open(POLLS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception as e:
        logging.warning(f"[client_alerts] Failed to load polls registry: {e}")
    return {}


def _save_polls_registry(registry: dict[str, dict]) -> None:
    """Saves polls registry mapping poll_id -> metadata (retaining last 500 polls)."""
    try:
        os.makedirs(os.path.dirname(POLLS_FILE), exist_ok=True)
        if len(registry) > 500:
            keys = list(registry.keys())[-500:]
            registry = {k: registry[k] for k in keys}
        with open(POLLS_FILE, "w", encoding="utf-8") as f:
            json.dump(registry, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"[client_alerts] Failed to save polls registry: {e}")


def _record_broadcast(
    preview: str,
    sent_map: dict[int, int],
    is_pinned: bool = False,
    poll_data: dict | None = None
) -> str:
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
        "reactions": {},
    }
    if poll_data:
        entry["poll"] = poll_data
    history = _load_broadcast_history()
    history.append(entry)
    _save_broadcast_history(history)
    return bc_id


def _record_client_reaction(user_id: int, message_id: int, reaction_str: str) -> str | None:
    """Records client reaction into the corresponding broadcast entry, if found."""
    history = _load_broadcast_history()
    uid_str = str(user_id)
    matched_bc_id = None
    for entry in reversed(history):
        sent = entry.get("sent", {})
        if sent.get(uid_str) == message_id:
            reactions = entry.setdefault("reactions", {})
            if reaction_str:
                reactions[uid_str] = reaction_str
            else:
                reactions.pop(uid_str, None)
            matched_bc_id = entry.get("id")
            _save_broadcast_history(history)
            break
    return matched_bc_id


def _record_poll_vote(bc_id: str, user_id: int, option_ids: list[int]) -> None:
    """Records user's poll answer or retraction into the broadcast entry."""
    history = _load_broadcast_history()
    uid_str = str(user_id)
    for entry in history:
        if entry.get("id") == bc_id and "poll" in entry:
            votes = entry["poll"].setdefault("votes", {})
            if option_ids:
                votes[uid_str] = option_ids
            else:
                votes.pop(uid_str, None)
            _save_broadcast_history(history)
            break


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
        elif message.poll:
            payload["type"] = "poll"
            payload["question"] = message.poll.question
            payload["options"] = [opt.text for opt in message.poll.options]
            payload["is_anonymous"] = message.poll.is_anonymous
            payload["allows_multiple_answers"] = message.poll.allows_multiple_answers
            payload["poll_type"] = message.poll.type
            payload["explanation"] = message.poll.explanation
        elif message.location:
            payload["type"] = "location"
            payload["latitude"] = message.location.latitude
            payload["longitude"] = message.location.longitude
        elif message.venue:
            payload["type"] = "venue"
            payload["latitude"] = message.venue.location.latitude
            payload["longitude"] = message.venue.location.longitude
            payload["title"] = message.venue.title
            payload["address"] = message.venue.address
        elif message.contact:
            payload["type"] = "contact"
            payload["phone_number"] = message.contact.phone_number
            payload["first_name"] = message.contact.first_name
            payload["last_name"] = message.contact.last_name
            payload["vcard"] = message.contact.vcard
        elif message.dice:
            payload["type"] = "dice"
            payload["emoji"] = message.dice.emoji
        elif message.caption and message.caption.strip():
            payload["type"] = "text"
            payload["text"] = message.caption
            if message.caption_entities:
                payload["entities"] = [dump_entity(e) for e in message.caption_entities]
        elif getattr(message, "html_text", None):
            payload["type"] = "text"
            payload["text"] = message.html_text
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
    elif msg_type == "poll":
        sent = await alert_bot.send_poll(
            chat_id,
            question=payload["question"],
            options=payload["options"],
            is_anonymous=payload.get("is_anonymous", True),
            allows_multiple_answers=payload.get("allows_multiple_answers", False),
            type=payload.get("poll_type", "regular"),
            explanation=payload.get("explanation"),
            **kwargs
        )
    elif msg_type == "location":
        sent = await alert_bot.send_location(
            chat_id,
            latitude=payload["latitude"],
            longitude=payload["longitude"],
            **kwargs
        )
    elif msg_type == "venue":
        sent = await alert_bot.send_venue(
            chat_id,
            latitude=payload["latitude"],
            longitude=payload["longitude"],
            title=payload["title"],
            address=payload["address"],
            **kwargs
        )
    elif msg_type == "contact":
        sent = await alert_bot.send_contact(
            chat_id,
            phone_number=payload["phone_number"],
            first_name=payload["first_name"],
            last_name=payload.get("last_name"),
            vcard=payload.get("vcard"),
            **kwargs
        )
    elif msg_type == "dice":
        sent = await alert_bot.send_dice(chat_id, emoji=payload.get("emoji", "🎲"), **kwargs)
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

def _get_alert_panel_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    """
    Alert Module management panel for administrators.
    Opens when clicking "📣 Write alert" button in the main bot.
    """
    subscribers = _load_subscribers()
    history = _load_broadcast_history()
    count_label = _("alert_label_count", lang).format(count=len(subscribers)) if subscribers else _("alert_label_empty", lang)
    hist_label = f"({len(history)})" if history else ""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_("alert_btn_broadcast", lang),
                    callback_data="alert_panel_broadcast",
                ),
                InlineKeyboardButton(
                    text=_("alert_btn_subscribers", lang).format(label=count_label),
                    callback_data="alert_panel_subscribers",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=_("alert_btn_delete_broadcast", lang).format(label=hist_label).strip(),
                    callback_data="alert_panel_history",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=_("btn_back_to_menu", lang),
                    callback_data="back_to_menu",
                ),
            ],
        ]
    )


def _get_broadcast_history_keyboard(history: list[dict], lang: str = "ru") -> InlineKeyboardMarkup:
    """Keyboard listing recent broadcasts for deletion."""
    keyboard = []
    for entry in reversed(history):
        bc_id = entry.get("id")
        date_str = entry.get("date_str", "")
        preview = entry.get("preview", "")
        btn_text = f"🗑 {date_str} — {preview[:22]}"
        keyboard.append([InlineKeyboardButton(text=btn_text, callback_data=f"alert_view_bc_{bc_id}")])
    keyboard.append([InlineKeyboardButton(text=_("btn_back", lang), callback_data="alert_fsm_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def _get_broadcast_delete_confirm_keyboard(broadcast_id: str, is_poll_or_has_reactions: bool = False, lang: str = "ru") -> InlineKeyboardMarkup:
    """Confirmation button before deleting broadcast across all subscribers."""
    rows = []
    if is_poll_or_has_reactions:
        rows.append([
            InlineKeyboardButton(
                text=_("alert_btn_refresh", lang),
                callback_data=f"alert_view_bc_{broadcast_id}"
            )
        ])
    rows.append([
        InlineKeyboardButton(
            text=_("alert_btn_confirm_del_all", lang),
            callback_data=f"alert_confirm_del_bc_{broadcast_id}"
        )
    ])
    rows.append([
        InlineKeyboardButton(
            text=_("alert_btn_back_to_list", lang),
            callback_data="alert_panel_history"
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _get_reply_keyboard(client_user_id: int, client_message_id: int, lang: str = "ru") -> InlineKeyboardMarkup:
    """Inline 'Reply' button under incoming administrator ticket."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_("alert_btn_reply", lang),
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
    btn_url: str | None = None,
    lang: str = "ru"
) -> str:
    """Renders broadcast parameters summary text."""
    btn_line = _("alert_button_line_set", lang).format(title=btn_title, url=btn_url) if btn_title and btn_url else _("alert_button_line_unset", lang)
    pin_line = _("alert_yes", lang) if pin else _("alert_no", lang)
    sound_line = _("alert_sound_line_silent", lang) if silent else _("alert_sound_line_loud", lang)

    return _("alert_broadcast_params_title", lang).format(
        count=subscribers_count,
        pin=pin_line,
        sound=sound_line,
        button=btn_line
    )


def _get_broadcast_confirm_keyboard(
    pin: bool = False,
    silent: bool = False,
    btn_info: str | None = None,
    lang: str = "ru"
) -> InlineKeyboardMarkup:
    """Broadcast confirmation or cancellation with advanced options."""
    pin_text = _("alert_btn_pin_on", lang) if pin else _("alert_btn_pin_off", lang)
    sound_text = _("alert_btn_sound_off", lang) if silent else _("alert_btn_sound_on", lang)
    btn_text = _("alert_btn_button_info", lang).format(info=btn_info[:14]) if btn_info else _("alert_btn_add_button", lang)

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
                    text=_("alert_btn_send_all", lang),
                    callback_data="alert_broadcast_confirm",
                ),
                InlineKeyboardButton(
                    text=_("btn_cancel", lang),
                    callback_data="alert_fsm_cancel",
                ),
            ],
        ]
    )


def _get_cancel_keyboard(lang: str = "ru") -> InlineKeyboardMarkup:
    """Cancel button for current FSM action."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_("btn_cancel", lang),
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
    lang = _get_client_lang(user_id)
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

    # Language toggle button
    keyboard.append([InlineKeyboardButton(text=_("alert_btn_client_lang", lang), callback_data="cst_toggle_lang")])
            
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# ─── Alert Bot: Handlers ───────────────────────────────────────────────────

if alert_dp is not None:

    @alert_dp.message(Command("start"))
    async def alert_start_handler(message: types.Message) -> None:
        """
        Client clicks /start in Alert Bot → subscribes to broadcast alerts.
        """
        user_id = message.from_user.id
        tg_lang = message.from_user.language_code
        user_name = message.from_user.full_name or f"ID {user_id}"
        is_new = await _add_subscriber(user_id, user_name, tg_lang)
        lang = _get_client_lang(user_id, tg_lang)

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

    @alert_dp.callback_query(F.data == "cst_toggle_lang")
    async def _cq_client_toggle_lang(callback: types.CallbackQuery):
        user_id = callback.from_user.id
        subscribers = _load_subscribers()
        if user_id in subscribers:
            cur = subscribers[user_id].get("lang", "ru")
            new_lang = "en" if cur == "ru" else "ru"
            subscribers[user_id]["lang"] = new_lang
            _save_subscribers(subscribers)
            try:
                await callback.message.edit_text(
                    _("alert_settings_text", new_lang),
                    parse_mode="HTML",
                    reply_markup=await _get_client_settings_keyboard(user_id)
                )
            except Exception as exc:
                logging.debug("Unable to update client settings language: %s", exc)
        await callback.answer()

    @alert_dp.callback_query(F.data == "cst_toggle_all")
    async def _cq_client_settings_toggle_all(callback: types.CallbackQuery):
        user_id = callback.from_user.id
        subscribers = _load_subscribers()
        s_data = subscribers.get(user_id, {})
        mute_all = s_data.get("mute_all", False)
        lang = _get_client_lang(user_id)

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
        lang = _get_client_lang(user_id)
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
        lang = _get_client_lang(user_id)
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

        user_id = message.from_user.id
        tg_lang = message.from_user.language_code
        user_name = message.from_user.full_name or f"ID {user_id}"
        await _add_subscriber(user_id, user_name, tg_lang)
        lang = _get_client_lang(user_id, tg_lang)

        if message.text in ["⚙️ Настройки", "⚙️ Settings", _("alert_btn_settings", "ru"), _("alert_btn_settings", "en"), "/settings"]:
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

        admin_lang = get_user_lang(config.ADMIN_USER_ID)
        username_str = (
            f"@{message.from_user.username}"
            if message.from_user.username
            else ("no username" if admin_lang == "en" else "нет username")
        )

        ticket_header = _("alert_ticket_header", admin_lang).format(
            user_name=html.escape(user_name),
            username_str=html.escape(username_str),
            user_id=user_id,
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
                reply_markup=_get_reply_keyboard(user_id, message.message_id, admin_lang),
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

    def _extract_reaction_emojis(reaction_list: list) -> str:
        res = []
        for r in reaction_list or []:
            if getattr(r, "emoji", None):
                res.append(r.emoji)
            elif getattr(r, "custom_emoji_id", None):
                res.append("⭐️")
            elif getattr(r, "type", None) == "paid":
                res.append("⭐️")
        return " ".join(res)

    @alert_dp.message_reaction()
    async def alert_reaction_handler(event: types.MessageReactionUpdated) -> None:
        """
        Subscribers add/remove reactions to messages → notify admin in main bot
        with a Reply button to contact the user.
        """
        if alert_bot is None:
            return
        user = getattr(event, "user", None)
        if not user or user.is_bot:
            return

        user_id = user.id
        user_name = user.full_name or f"ID {user_id}"
        username_str = f"@{user.username}" if user.username else "нет username"

        new_emojis = _extract_reaction_emojis(getattr(event, "new_reaction", None))
        old_emojis = _extract_reaction_emojis(getattr(event, "old_reaction", None))

        # Record in broadcast history if matches a broadcast message
        _record_client_reaction(user_id, event.message_id, new_emojis)

        # Lazy import of the main bot to avoid circular imports
        try:
            import bot as main_bot_module
            main_bot_instance: Bot = main_bot_module.bot
        except ImportError:
            logging.error("[client_alerts] Failed to import the main bot.")
            return

        lang = _get_bot_lang()
        safe_user_name = html.escape(user_name)
        safe_username_str = html.escape(username_str)

        if new_emojis:
            msg_text = _("alert_reaction_notify", lang).format(
                user_name=safe_user_name,
                username_str=safe_username_str,
                user_id=user_id,
                reaction=html.escape(new_emojis),
            )
        else:
            msg_text = _("alert_reaction_removed", lang).format(
                user_name=safe_user_name,
                username_str=safe_username_str,
                user_id=user_id,
                old_reaction=html.escape(old_emojis or "—"),
            )

        reply_kb = _get_reply_keyboard(user_id, event.message_id, lang)
        try:
            await main_bot_instance.send_message(
                config.ADMIN_USER_ID,
                msg_text,
                parse_mode="HTML",
                reply_markup=reply_kb,
            )
        except Exception as exc:
            logging.error("[client_alerts] Failed to notify admin about reaction: %s", exc)

    @alert_dp.poll_answer()
    async def alert_poll_answer_handler(poll_answer: types.PollAnswer) -> None:
        """
        Subscribers vote or retract answers in polls → update broadcast poll registry
        and notify admin in main bot with selected options and a Reply button.
        """
        if alert_bot is None:
            return
        user = getattr(poll_answer, "user", None)
        if not user or user.is_bot:
            return

        poll_id = str(getattr(poll_answer, "poll_id", ""))
        polls_reg = _load_polls_registry()
        poll_meta = polls_reg.get(poll_id)

        user_id = user.id
        user_name = user.full_name or f"ID {user_id}"
        username_str = f"@{user.username}" if user.username else "нет username"

        question = poll_meta.get("question", "Опрос") if poll_meta else "Опрос"
        options = poll_meta.get("options", []) if poll_meta else []
        bc_id = poll_meta.get("bc_id") if poll_meta else None
        msg_id = poll_meta.get("message_id", 0) if poll_meta else 0

        selected_ids = getattr(poll_answer, "option_ids", []) or []
        if bc_id:
            _record_poll_vote(bc_id, user_id, selected_ids)

        # Lazy import of the main bot to avoid circular imports
        try:
            import bot as main_bot_module
            main_bot_instance: Bot = main_bot_module.bot
        except ImportError:
            logging.error("[client_alerts] Failed to import the main bot.")
            return

        lang = _get_bot_lang()
        safe_user_name = html.escape(user_name)
        safe_username_str = html.escape(username_str)
        safe_question = html.escape(question)

        if selected_ids:
            selected_names = [options[i] for i in selected_ids if 0 <= i < len(options)]
            opts_str = ", ".join(f"«{o}»" for o in selected_names) if selected_names else str(selected_ids)
            msg_text = _("alert_poll_answer_notify", lang).format(
                user_name=safe_user_name,
                username_str=safe_username_str,
                user_id=user_id,
                question=safe_question,
                options=html.escape(opts_str),
            )
        else:
            msg_text = _("alert_poll_answer_retracted", lang).format(
                user_name=safe_user_name,
                username_str=safe_username_str,
                user_id=user_id,
                question=safe_question,
            )

        reply_kb = _get_reply_keyboard(user_id, msg_id, lang)
        try:
            await main_bot_instance.send_message(
                config.ADMIN_USER_ID,
                msg_text,
                parse_mode="HTML",
                reply_markup=reply_kb,
            )
        except Exception as exc:
            logging.error("[client_alerts] Failed to notify admin about poll answer: %s", exc)


# ─── Main Bot: Control Panel (callback) ───────────────────────────────────

async def _alert_panel_open(message: types.Message, state: FSMContext) -> None:
    """
    Button '📣 Write alert' clicked in main bot → show control panel.
    Available only to admin; regular users receive informational message.
    """
    user_id = message.from_user.id
    lang = get_user_lang(user_id)

    if user_id != config.ADMIN_USER_ID:
        # To regular users — info message instead of error
        await message.answer(
            _("alert_user_info_not_admin", lang),
            parse_mode="HTML",
        )
        return

    await state.clear()
    subscribers = _load_subscribers()
    status_str = _("alert_status_active", lang) if alert_bot else _("alert_status_inactive", lang)
    text = (
        f"{_('alert_admin_title', lang)}\n\n"
        f"{_('alert_admin_subscribers_count', lang).format(count=len(subscribers))}\n"
        f"{_('alert_admin_bot_status', lang).format(status=status_str)}\n\n"
        f"{_('alert_admin_choose_action', lang)}"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=_get_alert_panel_keyboard(lang))


async def _cq_panel_broadcast(callback: types.CallbackQuery, state: FSMContext) -> None:
    """
    Button '📣 Broadcast' in panel → switch to FSM waiting for broadcast message.
    """
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    if user_id != config.ADMIN_USER_ID:
        await callback.answer(_("alert_admin_access_denied", lang), show_alert=True)
        return

    subscribers = _load_subscribers()
    if not subscribers:
        await callback.answer(_("alert_admin_no_subscribers", lang), show_alert=True)
        return

    await state.set_state(BroadcastStates.waiting_broadcast_message)
    await state.update_data(panel_message_id=callback.message.message_id)
    await callback.answer()
    
    text = _("alert_broadcast_prompt", lang).format(count=len(subscribers))
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=_get_cancel_keyboard(lang))
    except Exception as exc:
        logging.debug("Unable to display broadcast prompt: %s", exc)


async def _cq_panel_subscribers(callback: types.CallbackQuery) -> None:
    """
    Button '👥 Subscribers' → display subscribers list directly in inline message.
    """
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    if user_id != config.ADMIN_USER_ID:
        await callback.answer(_("alert_admin_access_denied", lang), show_alert=True)
        return

    page = 1
    if callback.data.startswith("alert_panel_subscribers_page_"):
        page = int(callback.data.split("_")[-1])

    subscribers = _load_subscribers()
    await callback.answer()

    if not subscribers:
        text = _("alert_subscribers_empty", lang)
        markup = _get_alert_panel_keyboard(lang)
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
        
        text = _("alert_subscribers_title", lang).format(
            total=len(subscribers),
            page=page,
            total_pages=total_pages,
            list=ids_text
        )
        
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton(text=_("btn_page_prev", lang), callback_data=f"alert_panel_subscribers_page_{page - 1}"))
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton(text=_("btn_page_next", lang), callback_data=f"alert_panel_subscribers_page_{page + 1}"))
            
        keyboard = []
        if nav_buttons:
            keyboard.append(nav_buttons)
        keyboard.append([InlineKeyboardButton(text=_("btn_back", lang), callback_data="alert_fsm_cancel")])
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
    lang = get_user_lang(message.from_user.id)
    if payload.get("type") == "unsupported":
        logging.warning("[client_alerts] Unsupported message type for broadcast: %s", payload.get("debug", "")[:200])
        await message.answer(
            _("alert_broadcast_err_unsupported", lang),
            parse_mode="HTML"
        )
        return

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
    
    text = _render_broadcast_confirm_text(len(subscribers), pin=False, silent=False, btn_title=None, btn_url=None, lang=lang)
    markup = _get_broadcast_confirm_keyboard(pin=False, silent=False, btn_info=None, lang=lang)

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
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    if user_id != config.ADMIN_USER_ID:
        await callback.answer(_("alert_admin_access_denied", lang), show_alert=True)
        return
    data = await state.get_data()
    cur_pin = not data.get("broadcast_pin", False)
    await state.update_data(broadcast_pin=cur_pin)
    
    subscribers = _load_subscribers()
    silent = data.get("broadcast_silent", False)
    btn_title = data.get("btn_title")
    btn_url = data.get("btn_url")
    
    text = _render_broadcast_confirm_text(len(subscribers), cur_pin, silent, btn_title, btn_url, lang=lang)
    markup = _get_broadcast_confirm_keyboard(pin=cur_pin, silent=silent, btn_info=btn_title, lang=lang)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    except Exception as exc:
        logging.debug("Unable to update broadcast pin setting: %s", exc)
    await callback.answer()


async def _cq_broadcast_toggle_sound(callback: types.CallbackQuery, state: FSMContext) -> None:
    """Toggle silent delivery for broadcast."""
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    if user_id != config.ADMIN_USER_ID:
        await callback.answer(_("alert_admin_access_denied", lang), show_alert=True)
        return
    data = await state.get_data()
    cur_silent = not data.get("broadcast_silent", False)
    await state.update_data(broadcast_silent=cur_silent)
    
    subscribers = _load_subscribers()
    pin = data.get("broadcast_pin", False)
    btn_title = data.get("btn_title")
    btn_url = data.get("btn_url")
    
    text = _render_broadcast_confirm_text(len(subscribers), pin, cur_silent, btn_title, btn_url, lang=lang)
    markup = _get_broadcast_confirm_keyboard(pin=pin, silent=cur_silent, btn_info=btn_title, lang=lang)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    except Exception as exc:
        logging.debug("Unable to update broadcast sound setting: %s", exc)
    await callback.answer()


async def _cq_broadcast_setup_button(callback: types.CallbackQuery, state: FSMContext) -> None:
    """Ask administrator for custom inline button title and URL."""
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    if user_id != config.ADMIN_USER_ID:
        await callback.answer(_("alert_admin_access_denied", lang), show_alert=True)
        return
    await state.set_state(BroadcastStates.waiting_broadcast_button)
    await callback.answer()
    
    text = _("alert_button_setup_prompt", lang)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=_get_cancel_keyboard(lang))
    except Exception as exc:
        logging.debug("Unable to display setup button prompt: %s", exc)


async def _broadcast_button_received(message: types.Message, state: FSMContext) -> None:
    """Handles administrator input for broadcast inline button."""
    data = await state.get_data()
    panel_message_id = data.get("panel_message_id")
    raw_text = (message.text or "").strip()
    lang = get_user_lang(message.from_user.id)
    
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
                _("alert_button_err_invalid_url", lang),
                parse_mode="HTML"
            )
            return
    else:
        await message.answer(
            _("alert_button_err_format", lang),
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
    
    text = _render_broadcast_confirm_text(len(subscribers), pin, silent, btn_title, btn_url, lang=lang)
    markup = _get_broadcast_confirm_keyboard(pin=pin, silent=silent, btn_info=btn_title, lang=lang)
    
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
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    if user_id != config.ADMIN_USER_ID:
        await callback.answer(_("alert_admin_access_denied", lang), show_alert=True)
        return

    data = await state.get_data()
    payload = data.get("broadcast_payload")
    pin = data.get("broadcast_pin", False)
    silent = data.get("broadcast_silent", False)
    btn_title = data.get("btn_title")
    btn_url = data.get("btn_url")
    await state.clear()

    if not payload or payload.get("type") == "unsupported":
        await callback.answer(_("alert_broadcast_err_unsupported", lang), show_alert=True)
        return

    if alert_bot is None:
        await callback.answer(_("alert_bot_not_active", lang), show_alert=True)
        return

    subscribers = _load_subscribers()
    if not subscribers:
        await callback.answer(_("alert_admin_no_subscribers", lang), show_alert=True)
        return

    await callback.answer(_("alert_broadcast_starting", lang))
    try:
        await callback.message.edit_text(_("alert_broadcast_progress", lang), parse_mode="HTML", reply_markup=None)
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
    poll_id_map: dict[str, int] = {}

    is_poll = payload.get("type") == "poll"
    poll_data = None
    if is_poll:
        poll_data = {
            "question": payload.get("question", ""),
            "options": payload.get("options", []),
            "votes": {}
        }

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
                if is_poll and getattr(sent, "poll", None) and getattr(sent.poll, "id", None):
                    poll_id_map[str(sent.poll.id)] = uid
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
        no_text_label = "Media" if lang == "en" else "Медиа"
        preview_text = payload.get("text") or payload.get("caption") or (f"Poll: {payload.get('question')}" if (is_poll and lang == "en") else (f"Опрос: {payload.get('question')}" if is_poll else f"{no_text_label} ({payload.get('type')})"))
        bc_id = _record_broadcast(preview_text, sent_messages, is_pinned=bool(pin), poll_data=poll_data)
        if is_poll and poll_id_map:
            polls_reg = _load_polls_registry()
            for pid, uid in poll_id_map.items():
                polls_reg[pid] = {
                    "bc_id": bc_id,
                    "user_id": uid,
                    "message_id": sent_messages.get(uid, 0),
                    "question": payload.get("question", ""),
                    "options": payload.get("options", [])
                }
            _save_polls_registry(polls_reg)

    result_text = _("alert_broadcast_finished", lang).format(sent_ok=sent_ok, sent_fail=sent_fail)

    if bc_id:
        result_markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=_("alert_btn_revoke_all", lang),
                        callback_data=f"alert_confirm_del_bc_{bc_id}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=_("alert_btn_back_to_panel", lang),
                        callback_data="alert_panel_open_again"
                    ),
                    InlineKeyboardButton(
                        text=_("btn_back_to_menu", lang),
                        callback_data="back_to_menu"
                    ),
                ]
            ]
        )
    else:
        result_markup = _get_alert_panel_keyboard(lang)

    try:
        await callback.message.edit_text(result_text, parse_mode="HTML", reply_markup=result_markup)
    except Exception as exc:
        logging.debug("Unable to display broadcast result: %s", exc)


async def _cq_panel_open_again(callback: types.CallbackQuery, state: FSMContext) -> None:
    """Return to alert panel menu."""
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    if user_id != config.ADMIN_USER_ID:
        await callback.answer(_("alert_admin_access_denied", lang), show_alert=True)
        return
    await state.clear()
    subscribers = _load_subscribers()
    status_str = _("alert_status_active", lang) if alert_bot else _("alert_status_inactive", lang)
    text = (
        f"{_('alert_admin_title', lang)}\n\n"
        f"{_('alert_admin_subscribers_count', lang).format(count=len(subscribers))}\n"
        f"{_('alert_admin_bot_status', lang).format(status=status_str)}\n\n"
        f"{_('alert_admin_choose_action', lang)}"
    )
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=_get_alert_panel_keyboard(lang))
    except Exception as exc:
        logging.debug("Unable to return to alert panel: %s", exc)
    await callback.answer()


async def _cq_panel_history(callback: types.CallbackQuery) -> None:
    """Display list of recent broadcasts available for deletion."""
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    if user_id != config.ADMIN_USER_ID:
        await callback.answer(_("alert_admin_access_denied", lang), show_alert=True)
        return

    history = _load_broadcast_history()
    if not history:
        await callback.answer(_("alert_history_empty", lang), show_alert=True)
        return

    await callback.answer()
    text = _("alert_history_title", lang)
    markup = _get_broadcast_history_keyboard(history, lang)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    except Exception as exc:
        logging.debug("Unable to display broadcast history: %s", exc)


async def _cq_view_broadcast(callback: types.CallbackQuery) -> None:
    """Show details of selected broadcast, poll/reaction statistics, and ask for deletion confirmation."""
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    if user_id != config.ADMIN_USER_ID:
        await callback.answer(_("alert_admin_access_denied", lang), show_alert=True)
        return

    bc_id = callback.data.replace("alert_view_bc_", "")
    history = _load_broadcast_history()
    target = next((item for item in history if item.get("id") == bc_id), None)

    if not target:
        await callback.answer(_("alert_broadcast_not_found", lang), show_alert=True)
        return

    await callback.answer()
    recipients_count = len(target.get("sent", {}))
    poll = target.get("poll")
    reactions = target.get("reactions", {})
    extra_info = ""

    if poll:
        question = poll.get("question", "")
        options = poll.get("options", [])
        votes = poll.get("votes", {})
        total_voters = len(votes)
        counts = [0] * len(options)
        for u_opts in votes.values():
            for opt_idx in u_opts:
                if 0 <= opt_idx < len(counts):
                    counts[opt_idx] += 1
        extra_info += "\n\n" + _("alert_poll_results_header", lang).format(question=html.escape(question))
        for idx, opt_name in enumerate(options):
            c = counts[idx]
            pct = (c / total_voters * 100) if total_voters > 0 else 0.0
            extra_info += f"• {html.escape(opt_name)}: <b>{c}</b> ({pct:.1f}%)\n"
        extra_info += _("alert_poll_total_voters", lang).format(total=total_voters) + "\n"

    if reactions:
        from collections import Counter
        emoji_counts = Counter(reactions.values())
        extra_info += "\n\n" + _("alert_reactions_header", lang)
        for emoji_char, count in emoji_counts.most_common():
            extra_info += f"• {html.escape(emoji_char)} — <b>{count}</b>\n"
        extra_info += _("alert_reactions_total", lang).format(total=len(reactions)) + "\n"

    no_text_label = "No text" if lang == "en" else "Без текста"
    preview_escaped = html.escape(target.get("preview", no_text_label))
    text = _("alert_delete_confirm_prompt", lang).format(
        date=target.get('date_str', 'Unknown' if lang == 'en' else 'Неизвестно'),
        preview=preview_escaped,
        recipients=recipients_count,
        extra=extra_info
    )
    markup = _get_broadcast_delete_confirm_keyboard(bc_id, is_poll_or_has_reactions=bool(poll or reactions), lang=lang)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    except Exception as exc:
        logging.debug("Unable to display delete confirmation: %s", exc)


async def _cq_confirm_delete_broadcast(callback: types.CallbackQuery) -> None:
    """Execute broadcast message deletion across all subscribers."""
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    if user_id != config.ADMIN_USER_ID:
        await callback.answer(_("alert_admin_access_denied", lang), show_alert=True)
        return

    bc_id = callback.data.replace("alert_confirm_del_bc_", "")
    await callback.answer(_("alert_deleting_progress", lang))
    try:
        await callback.message.edit_text(
            _("alert_deleting_progress", lang),
            parse_mode="HTML"
        )
    except Exception as exc:
        logging.debug("Unable to display deletion progress: %s", exc)

    del_ok, del_fail = await _delete_broadcast_for_all(bc_id)

    result_text = _("alert_delete_result", lang).format(del_ok=del_ok, del_fail=del_fail)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=_("alert_btn_back_to_panel", lang), callback_data="alert_panel_open_again"),
                InlineKeyboardButton(text=_("btn_back_to_menu", lang), callback_data="back_to_menu"),
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
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    if user_id != config.ADMIN_USER_ID:
        await callback.answer(_("alert_admin_access_denied", lang), show_alert=True)
        return

    try:
        parts = callback.data.split("_")
        client_user_id = int(parts[2])
        client_message_id = int(parts[3])
    except (IndexError, ValueError):
        await callback.answer("⚠️ Некорректный ID клиента или сообщения." if lang != "en" else "⚠️ Invalid client or message ID.", show_alert=True)
        return

    await state.set_state(ReplyStates.waiting_reply_text)
    await state.update_data(reply_to_user_id=client_user_id, reply_to_message_id=client_message_id, panel_message_id=callback.message.message_id)

    await callback.answer()
    
    text = _("alert_reply_prompt", lang).format(user_id=client_user_id)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=_get_cancel_keyboard(lang))
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
    lang = get_user_lang(message.from_user.id)

    if not client_user_id:
        await message.answer(_("alert_reply_client_not_found", lang))
        return

    if alert_bot is None:
        await message.answer(_("alert_reply_bot_inactive", lang))
        return

    payload = await _extract_message_payload(message)
    
    try:
        await message.delete()
    except Exception as exc:
        logging.debug("Unable to delete alert reply input message: %s", exc)

    try:
        await _send_payload_via_alert_bot(client_user_id, payload, reply_to_message_id=client_message_id)
        logging.info(f"[client_alerts] Reply sent to client {client_user_id}.")
        text = _("alert_reply_success", lang).format(user_id=client_user_id)
    except Exception as e:
        logging.error(f"[client_alerts] Error replying to client {client_user_id}: {e}")
        text = _("alert_reply_fail", lang).format(user_id=client_user_id, error=e)

    full_text = f"{text}\n\n{_('alert_admin_choose_action', lang)}"
    try:
        import bot as main_bot_module
        main_bot_instance: Bot = main_bot_module.bot
        await main_bot_instance.edit_message_text(
            chat_id=message.chat.id,
            message_id=panel_message_id,
            text=full_text,
            parse_mode="HTML",
            reply_markup=_get_alert_panel_keyboard(lang)
        )
    except Exception:
        await message.answer(full_text, parse_mode="HTML", reply_markup=_get_alert_panel_keyboard(lang))


# ─── Main Bot: General FSM cancellation via button ─────────────────────────────────

async def _cq_fsm_cancel(callback: types.CallbackQuery, state: FSMContext) -> None:
    """
    Button '❌ Cancel' during any FSM input (broadcast, reply).
    If in button input mode, returns to broadcast preview.
    Otherwise resets state and returns to control panel.
    """
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    current_state = await state.get_state()
    if current_state == BroadcastStates.waiting_broadcast_button.state:
        await state.set_state(BroadcastStates.waiting_broadcast_message)
        data = await state.get_data()
        pin = data.get("broadcast_pin", False)
        silent = data.get("broadcast_silent", False)
        btn_title = data.get("btn_title")
        btn_url = data.get("btn_url")
        subscribers = _load_subscribers()
        text = _render_broadcast_confirm_text(len(subscribers), pin, silent, btn_title, btn_url, lang=lang)
        markup = _get_broadcast_confirm_keyboard(pin=pin, silent=silent, btn_info=btn_title, lang=lang)
        try:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
        except Exception as exc:
            logging.debug("Unable to restore broadcast menu: %s", exc)
        await callback.answer(_("alert_fsm_button_cancelled", lang))
        return

    await state.clear()
    subscribers = _load_subscribers()
    status_str = _("alert_status_active", lang) if alert_bot else _("alert_status_inactive", lang)
    text = (
        f"{_('alert_admin_title', lang)}\n\n"
        f"{_('alert_admin_subscribers_count', lang).format(count=len(subscribers))}\n"
        f"{_('alert_admin_bot_status', lang).format(status=status_str)}\n\n"
        f"{_('alert_admin_choose_action', lang)}"
    )
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=_get_alert_panel_keyboard(lang))
    except Exception as exc:
        logging.debug("Unable to display cancelled alert menu: %s", exc)
    await callback.answer(_("alert_fsm_cancelled", lang))


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
                allowed_updates=list(set((alert_dp.resolve_used_update_types() or []) + ["message", "callback_query", "message_reaction", "poll_answer"])),
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
