import os
import glob
import json
import asyncio
import logging
import time
import zipfile
import psutil
from datetime import datetime
from aiogram import Dispatcher, types, F
from aiogram.types import KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from core.i18n import I18nFilter, get_user_lang, get_text
from core import i18n as i18n_module
from core import config
from core import utils as core_utils
from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message
from core.shared_state import LAST_MESSAGE_IDS
from core.keyboards import get_backups_menu_keyboard, get_backup_timer_settings_keyboard
from core.utils import format_traffic
from modules import traffic as traffic_module

BUTTON_KEY = "btn_backups"
MAX_BACKUPS_PER_TYPE = 5
BACKUP_INTERVAL_STEP = 30
BACKUP_INTERVAL_THRESHOLD = 600

BACKUP_TYPES = {
    "traffic": {
        "dir": config.TRAFFIC_BACKUP_DIR,
        "pattern": "traffic_backup_*.json",
        "title_key": "traffic_backup_menu_title",
        "explanation_key": "traffic_backup_explanation",
        "create_callback": "create_traffic_backup",
    },
    "config": {
        "dir": config.CONFIG_BACKUP_DIR,
        "pattern": "config_backup_*.zip",
        "title_key": "config_backup_menu_title",
        "explanation_key": "config_backup_explanation",
        "create_callback": "create_backup_config",
    },
    "logs": {
        "dir": config.LOGS_BACKUP_DIR,
        "pattern": "logs_backup_*.zip",
        "title_key": "logs_backup_menu_title",
        "explanation_key": "logs_backup_explanation",
        "create_callback": "create_backup_logs",
    },
    "nodes": {
        "dir": config.NODES_BACKUP_DIR,
        "pattern": "nodes_backup_*.zip",
        "title_key": "nodes_backup_menu_title",
        "explanation_key": "nodes_backup_explanation",
        "create_callback": "create_backup_nodes",
    },
}


def _is_settings_allowed(user_id: int) -> bool:
    return is_allowed(user_id, "settings")


def _list_backup_files(backup_type: str) -> list[str]:
    cfg = BACKUP_TYPES[backup_type]
    return sorted(
        glob.glob(os.path.join(cfg["dir"], cfg["pattern"])),
        key=lambda p: os.path.getmtime(p),
        reverse=True,
    )


def _rotate_backups(backup_type: str):
    files = list(reversed(_list_backup_files(backup_type)))
    while len(files) > MAX_BACKUPS_PER_TYPE:
        oldest = files.pop(0)
        try:
            os.remove(oldest)
        except Exception as exc:
            logging.error(f"Failed to remove old {backup_type} backup {oldest}: {exc}")


def _create_zip_from_dir(backup_dir: str, prefix: str, source_dir: str, skip_dirs: set[str] | None = None):
    timestamp = int(time.time())
    filename = f"{prefix}_backup_{timestamp}.zip"
    filepath = os.path.join(backup_dir, filename)
    skip_dirs = skip_dirs or set()
    os.makedirs(backup_dir, exist_ok=True)

    with zipfile.ZipFile(filepath, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(source_dir):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for name in files:
                full_path = os.path.join(root, name)
                rel_path = os.path.relpath(full_path, source_dir)
                zf.write(full_path, arcname=rel_path)

    return filepath


def _create_backup_file(backup_type: str):
    if backup_type == "traffic":
        before = set(_list_backup_files("traffic"))
        rx, tx = traffic_module.get_current_traffic_total()
        traffic_module.save_backup_file(rx, tx)
        after = _list_backup_files("traffic")
        for path in after:
            if path not in before:
                return path
        return after[0] if after else None

    if backup_type == "config":
        created = _create_zip_from_dir(config.CONFIG_BACKUP_DIR, "config", config.CONFIG_DIR)
    elif backup_type == "logs":
        skip_dirs = {
            os.path.basename(config.TRAFFIC_BACKUP_DIR),
            os.path.basename(config.CONFIG_BACKUP_DIR),
            os.path.basename(config.LOGS_BACKUP_DIR),
            os.path.basename(config.NODES_BACKUP_DIR),
        }
        created = _create_zip_from_dir(config.LOGS_BACKUP_DIR, "logs", config.LOG_DIR, skip_dirs=skip_dirs)
    elif backup_type == "nodes":
        os.makedirs(config.NODES_BACKUP_DIR, exist_ok=True)
        timestamp = int(time.time())
        filename = f"nodes_backup_{timestamp}.zip"
        filepath = os.path.join(config.NODES_BACKUP_DIR, filename)
        nodes_db_path = os.path.join(config.CONFIG_DIR, "nodes.db")
        legacy_nodes_json = os.path.join(config.CONFIG_DIR, "nodes.json")
        with zipfile.ZipFile(filepath, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            if os.path.exists(nodes_db_path):
                zf.write(nodes_db_path, arcname="nodes.db")
            if os.path.exists(legacy_nodes_json):
                zf.write(legacy_nodes_json, arcname="nodes.json")
        created = filepath
    else:
        return None

    _rotate_backups(backup_type)
    return created


def _get_backups_menu_text(lang: str) -> str:
    current = int(getattr(config, "BACKUP_INTERVAL", 0) or 0)
    if current >= BACKUP_INTERVAL_STEP:
        status = get_text("backup_interval_status_on", lang, value=_format_interval_human(current, lang))
    else:
        status = get_text("backup_interval_status_off", lang)
    return f"{get_text('backups_menu_title', lang)}\n\n{status}"


def _normalize_interval(value: int) -> int:
    if value < BACKUP_INTERVAL_STEP:
        return 0
    return (value // BACKUP_INTERVAL_STEP) * BACKUP_INTERVAL_STEP


def _is_autobackup_enabled() -> bool:
    return int(getattr(config, "BACKUP_INTERVAL", 0) or 0) >= BACKUP_INTERVAL_STEP


def _format_interval_human(seconds: int, lang: str) -> str:
    if seconds < BACKUP_INTERVAL_STEP:
        return get_text("backup_interval_disabled_plain", lang)

    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    parts = []
    if days:
        parts.append(get_text("time_part_days", lang, value=days))
    if hours:
        parts.append(get_text("time_part_hours", lang, value=hours))
    if minutes:
        parts.append(get_text("time_part_minutes", lang, value=minutes))
    if secs or not parts:
        parts.append(get_text("time_part_seconds", lang, value=secs))
    return " ".join(parts)


def _adjust_backup_interval(direction: int) -> int:
    current = int(getattr(config, "BACKUP_INTERVAL", 0) or 0)

    if direction > 0:
        if current < BACKUP_INTERVAL_STEP:
            new_value = BACKUP_INTERVAL_STEP
        elif current < BACKUP_INTERVAL_THRESHOLD:
            new_value = current + BACKUP_INTERVAL_STEP
        else:
            new_value = current * 2
    else:
        if current < BACKUP_INTERVAL_STEP:
            new_value = 0
        elif current <= BACKUP_INTERVAL_STEP:
            new_value = 0
        elif current <= BACKUP_INTERVAL_THRESHOLD:
            new_value = current - BACKUP_INTERVAL_STEP
        else:
            new_value = current // 2

    new_value = _normalize_interval(new_value)
    payload = {"BACKUP_INTERVAL": new_value}
    if new_value >= BACKUP_INTERVAL_STEP:
        payload["BACKUP_LAST_INTERVAL"] = new_value
    config.save_system_config(payload)
    return new_value


def _toggle_autobackup() -> tuple[bool, int]:
    current = int(getattr(config, "BACKUP_INTERVAL", 0) or 0)
    if current >= BACKUP_INTERVAL_STEP:
        config.save_system_config({
            "BACKUP_LAST_INTERVAL": current,
            "BACKUP_INTERVAL": 0,
        })
        return False, 0

    last_value = int(getattr(config, "BACKUP_LAST_INTERVAL", 0) or 0)
    if last_value < BACKUP_INTERVAL_STEP:
        last_value = int(config.DEFAULT_CONFIG.get("BACKUP_INTERVAL", 300))
    last_value = _normalize_interval(last_value)
    if last_value < BACKUP_INTERVAL_STEP:
        last_value = BACKUP_INTERVAL_STEP

    config.save_system_config({
        "BACKUP_INTERVAL": last_value,
        "BACKUP_LAST_INTERVAL": last_value,
    })
    return True, last_value


def _get_auto_interval_label(lang: str) -> str:
    current = int(getattr(config, "BACKUP_INTERVAL", 0) or 0)
    return _format_interval_human(current, lang)


def _get_timer_settings_text(lang: str) -> str:
    current = _get_auto_interval_label(lang)
    return get_text("backup_timer_settings_text", lang, current=current)


def _get_backup_delete_menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=get_text("btn_backup_traffic", lang), callback_data="open_traffic_backups"),
                InlineKeyboardButton(text=get_text("btn_backup_config", lang), callback_data="open_config_backups"),
            ],
            [
                InlineKeyboardButton(text=get_text("btn_backup_logs", lang), callback_data="open_logs_backups"),
                InlineKeyboardButton(text=get_text("btn_backup_nodes", lang), callback_data="open_nodes_backups"),
            ],
            [
                InlineKeyboardButton(text=get_text("btn_backup_delete_all", lang), callback_data="confirm_delete_all_backups"),
            ],
            [
                InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="back_to_backups_main", style="primary"),
            ],
        ]
    )


def _get_delete_all_confirm_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=get_text("btn_confirm", lang), callback_data="do_delete_all_backups"),
                InlineKeyboardButton(text=get_text("btn_cancel", lang), callback_data="open_backup_delete_menu"),
            ],
            [
                InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="open_backup_delete_menu", style="primary"),
            ],
        ]
    )


def _delete_all_backups() -> int:
    deleted = 0
    for cfg in BACKUP_TYPES.values():
        for path in glob.glob(os.path.join(cfg["dir"], cfg["pattern"])):
            try:
                os.remove(path)
                deleted += 1
            except Exception as exc:
                logging.error(f"Failed to delete backup file {path}: {exc}")
    return deleted


def _restore_backup_file(backup_type: str, filepath: str) -> bool:
    if backup_type == "traffic":
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        backup_rx = int(data.get("rx", 0))
        backup_tx = int(data.get("tx", 0))
        counters = psutil.net_io_counters()
        traffic_module.TRAFFIC_OFFSET["rx"] = backup_rx - counters.bytes_recv
        traffic_module.TRAFFIC_OFFSET["tx"] = backup_tx - counters.bytes_sent
        traffic_module.IS_SERVER_REBOOT = True
        traffic_module.save_backup_file(backup_rx, backup_tx)
        return True

    if backup_type == "config":
        with zipfile.ZipFile(filepath, "r") as zf:
            zf.extractall(config.CONFIG_DIR)
        config.load_system_config()
        config.load_keyboard_config()
        core_utils.load_alerts_config()
        core_utils.load_services_config()
        i18n_module.load_user_settings()
        return True

    if backup_type == "logs":
        with zipfile.ZipFile(filepath, "r") as zf:
            zf.extractall(config.LOG_DIR)
        return True

    if backup_type == "nodes":
        with zipfile.ZipFile(filepath, "r") as zf:
            names = set(zf.namelist())
            for name in ("nodes.db", "nodes.json"):
                if name not in names:
                    continue
                data = zf.read(name)
                target = os.path.join(config.CONFIG_DIR, name)
                tmp_target = target + ".restore.tmp"
                with open(tmp_target, "wb") as f:
                    f.write(data)
                os.replace(tmp_target, target)
        return True

    return False


async def _send_backup_file_to_chat(callback: types.CallbackQuery, backup_type: str, file_path: str | None):
    if not file_path or not os.path.exists(file_path):
        return

    lang = get_user_lang(callback.from_user.id)
    try:
        with open(file_path, "rb") as f:
            payload = f.read()
        doc = BufferedInputFile(payload, filename=os.path.basename(file_path))
        caption = get_text("backup_file_sent_caption", lang, backup_type=backup_type)
        await callback.message.answer_document(document=doc, caption=caption)
    except Exception as exc:
        logging.error(f"Failed to send backup file to chat: {exc}")


def _format_file_size(size_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    value = float(max(0, size_bytes))
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} {unit}"
        value /= 1024
    return f"{int(size_bytes)} B"


def _format_backup_line(path: str, lang: str, backup_type: str) -> str:
    if backup_type == "traffic":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        date_str = data.get("date", "Unknown")
        rx = format_traffic(data.get("rx", 0), lang)
        tx = format_traffic(data.get("tx", 0), lang)
        return f"📂 <b>{date_str}</b>\n└ ⬇️{rx} | ⬆️{tx}"

    ts = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M:%S")
    size = _format_file_size(os.path.getsize(path))
    return f"📦 <b>{ts}</b>\n└ {size}"


async def start_background_tasks(_bot) -> list[asyncio.Task]:
    task = asyncio.create_task(periodic_backups_task(), name="GenericBackups")
    return [task]


async def periodic_backups_task():
    while True:
        interval = int(getattr(config, "BACKUP_INTERVAL", 0) or 0)
        if interval < BACKUP_INTERVAL_STEP:
            await asyncio.sleep(BACKUP_INTERVAL_STEP)
            continue

        await asyncio.sleep(interval)
        for backup_type in ("config", "logs", "nodes"):
            try:
                await asyncio.to_thread(_create_backup_file, backup_type)
            except Exception as exc:
                logging.error(f"Auto-backup failed for {backup_type}: {exc}")

def get_button() -> KeyboardButton:
    return KeyboardButton(text=get_text(BUTTON_KEY, config.DEFAULT_LANGUAGE))

def register_handlers(dp: Dispatcher):
    dp.message(I18nFilter(BUTTON_KEY))(backups_main_menu_handler)
    dp.callback_query(F.data == "back_to_backups_main")(backups_main_menu_callback)
    dp.callback_query(F.data == "close_backups_menu")(close_menu_handler)
    dp.callback_query(F.data == "open_traffic_backups")(traffic_backup_ui_handler)
    dp.callback_query(F.data == "open_config_backups")(config_backup_ui_handler)
    dp.callback_query(F.data == "open_logs_backups")(logs_backup_ui_handler)
    dp.callback_query(F.data == "open_nodes_backups")(nodes_backup_ui_handler)
    dp.callback_query(F.data == "create_traffic_backup")(create_traffic_backup_handler)
    dp.callback_query(F.data == "create_backup_config")(create_config_backup_handler)
    dp.callback_query(F.data == "create_backup_logs")(create_logs_backup_handler)
    dp.callback_query(F.data == "create_backup_nodes")(create_nodes_backup_handler)
    dp.callback_query(F.data == "open_backup_delete_menu")(open_backup_delete_menu_handler)
    dp.callback_query(F.data == "confirm_delete_all_backups")(confirm_delete_all_backups_handler)
    dp.callback_query(F.data == "do_delete_all_backups")(do_delete_all_backups_handler)
    dp.callback_query(F.data == "open_backup_timer_settings")(backup_timer_settings_handler)
    dp.callback_query(F.data == "backup_interval_inc")(backup_interval_inc_handler)
    dp.callback_query(F.data == "backup_interval_dec")(backup_interval_dec_handler)
    dp.callback_query(F.data == "backup_interval_reset")(backup_interval_reset_handler)
    dp.callback_query(F.data == "backup_toggle_enabled")(backup_toggle_enabled_handler)
    dp.callback_query(F.data == "backup_interval_noop")(backup_interval_noop_handler)
    dp.callback_query(F.data.startswith("restore_backup_"))(restore_backup_handler)
    dp.callback_query(F.data.startswith("delete_backup_"))(delete_backup_handler)


async def backups_main_menu_handler(message: types.Message):
    """Entry to backups main menu (via reply button)"""
    user_id = message.from_user.id
    chat_id = message.chat.id
    lang = get_user_lang(user_id)
    
    if not is_allowed(user_id, "settings"):
        await send_access_denied_message(message.bot, user_id, chat_id, "settings")
        return

    await delete_previous_message(
        user_id,
        list(LAST_MESSAGE_IDS.get(user_id, {}).keys()),
        chat_id,
        message.bot,
    )

    text = _get_backups_menu_text(lang)
    kb = get_backups_menu_keyboard(lang, get_text("backup_interval_value", lang, value=_get_auto_interval_label(lang)))
    
    sent_msg = await message.answer(text, reply_markup=kb, parse_mode="HTML")
    LAST_MESSAGE_IDS.setdefault(user_id, {})["backups_menu"] = sent_msg.message_id


async def backups_main_menu_callback(callback: types.CallbackQuery):
    """Return to backups main menu (Back button)"""
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    text = _get_backups_menu_text(lang)
    kb = get_backups_menu_keyboard(lang, get_text("backup_interval_value", lang, value=_get_auto_interval_label(lang)))
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


async def backup_interval_inc_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    if not _is_settings_allowed(user_id):
        await callback.answer(get_text("access_denied_generic", lang), show_alert=True)
        return

    new_value = _adjust_backup_interval(1)
    await callback.answer(get_text("backup_interval_changed", lang, value=_format_interval_human(new_value, lang)))
    await backup_timer_settings_handler(callback)


async def backup_interval_dec_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    if not _is_settings_allowed(user_id):
        await callback.answer(get_text("access_denied_generic", lang), show_alert=True)
        return

    new_value = _adjust_backup_interval(-1)
    if new_value < BACKUP_INTERVAL_STEP:
        await callback.answer(get_text("backup_interval_disabled_notice", lang))
    else:
        await callback.answer(get_text("backup_interval_changed", lang, value=_format_interval_human(new_value, lang)))
    await backup_timer_settings_handler(callback)


async def backup_timer_settings_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    if not _is_settings_allowed(user_id):
        await callback.answer(get_text("access_denied_generic", lang), show_alert=True)
        return

    text = _get_timer_settings_text(lang)
    kb = get_backup_timer_settings_keyboard(lang, _is_autobackup_enabled())
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


async def backup_toggle_enabled_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    if not _is_settings_allowed(user_id):
        await callback.answer(get_text("access_denied_generic", lang), show_alert=True)
        return

    enabled, value = _toggle_autobackup()
    if enabled:
        await callback.answer(get_text("backup_toggle_enabled_toast", lang, value=_format_interval_human(value, lang)))
    else:
        await callback.answer(get_text("backup_toggle_disabled_toast", lang))
    await backup_timer_settings_handler(callback)


async def backup_interval_noop_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    current = int(getattr(config, "BACKUP_INTERVAL", 0) or 0)
    if current < BACKUP_INTERVAL_STEP:
        await callback.answer(get_text("backup_interval_disabled_notice", lang), show_alert=True)
        return

    await callback.answer(
        get_text("backup_next_due_alert", lang, value=_format_interval_human(current, lang)),
        show_alert=True,
    )


async def backup_interval_reset_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    if not _is_settings_allowed(user_id):
        await callback.answer(get_text("access_denied_generic", lang), show_alert=True)
        return

    default_value = int(config.DEFAULT_CONFIG.get("BACKUP_INTERVAL", 300))
    config.save_system_config({"BACKUP_INTERVAL": default_value})
    await callback.answer(get_text("backup_interval_reset_done", lang, value=_format_interval_human(default_value, lang)))
    await backup_timer_settings_handler(callback)


async def open_backup_delete_menu_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    if not _is_settings_allowed(user_id):
        await callback.answer(get_text("access_denied_generic", lang), show_alert=True)
        return

    text = get_text("backup_delete_menu_text", lang)
    kb = _get_backup_delete_menu_keyboard(lang)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


async def confirm_delete_all_backups_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    if not _is_settings_allowed(user_id):
        await callback.answer(get_text("access_denied_generic", lang), show_alert=True)
        return

    text = get_text("backup_delete_all_confirm_text", lang)
    kb = _get_delete_all_confirm_keyboard(lang)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


async def do_delete_all_backups_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    lang = get_user_lang(user_id)
    if not _is_settings_allowed(user_id):
        await callback.answer(get_text("access_denied_generic", lang), show_alert=True)
        return

    deleted = await asyncio.to_thread(_delete_all_backups)
    await callback.answer(get_text("backup_delete_all_done", lang, count=deleted), show_alert=True)
    await open_backup_delete_menu_handler(callback)


async def _show_backup_ui(callback: types.CallbackQuery, backup_type: str):
    if backup_type not in BACKUP_TYPES:
        await callback.answer("Unknown backup type", show_alert=True)
        return

    user_id = callback.from_user.id
    if not _is_settings_allowed(user_id):
        await callback.answer(get_text("access_denied_generic", get_user_lang(user_id)), show_alert=True)
        return

    lang = get_user_lang(user_id)
    auto_interval = _get_auto_interval_label(lang)
    backups = _list_backup_files(backup_type)
    cfg = BACKUP_TYPES[backup_type]
    explanation = get_text(cfg["explanation_key"], lang, auto_interval=auto_interval)
    header = get_text(cfg["title_key"], lang)
    text = f"{explanation}\n{header}\n"

    buttons = []

    if not backups:
        text += f"\n{get_text('no_backups', lang)}"
    else:
        text += "\n"
        for backup_path in backups:
            try:
                filename = os.path.basename(backup_path)
                text += _format_backup_line(backup_path, lang, backup_type) + "\n"
                buttons.append(
                    [
                        InlineKeyboardButton(
                            text=f"♻️ {get_text('btn_restore_backup', lang)}",
                            callback_data=f"restore_backup_{backup_type}_{filename}",
                        ),
                        InlineKeyboardButton(
                            text=f"🗑 {get_text('btn_delete', lang)}",
                            callback_data=f"delete_backup_{backup_type}_{filename}",
                        ),
                    ]
                )
            except Exception as exc:
                logging.debug(f"Failed to render backup line for {backup_path}: {exc}")

    buttons.insert(
        0,
        [
            InlineKeyboardButton(
                text=get_text("btn_create_backup", lang),
                callback_data=cfg["create_callback"],
            )
        ],
    )
    buttons.append([InlineKeyboardButton(text=f"{get_text('btn_back', lang)}", callback_data="back_to_backups_main", style="primary")])

    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")


async def traffic_backup_ui_handler(callback: types.CallbackQuery):
    await _show_backup_ui(callback, "traffic")


async def config_backup_ui_handler(callback: types.CallbackQuery):
    await _show_backup_ui(callback, "config")


async def logs_backup_ui_handler(callback: types.CallbackQuery):
    await _show_backup_ui(callback, "logs")


async def nodes_backup_ui_handler(callback: types.CallbackQuery):
    await _show_backup_ui(callback, "nodes")


async def _create_backup_and_refresh(callback: types.CallbackQuery, backup_type: str):
    user_id = callback.from_user.id
    if not _is_settings_allowed(user_id):
        await callback.answer(get_text("access_denied_generic", get_user_lang(user_id)), show_alert=True)
        return

    created_path = await asyncio.to_thread(_create_backup_file, backup_type)
    await callback.answer(get_text("backup_created", get_user_lang(user_id)))
    await _send_backup_file_to_chat(callback, backup_type, created_path)
    await _show_backup_ui(callback, backup_type)


async def create_traffic_backup_handler(callback: types.CallbackQuery):
    await _create_backup_and_refresh(callback, "traffic")


async def create_config_backup_handler(callback: types.CallbackQuery):
    await _create_backup_and_refresh(callback, "config")


async def create_logs_backup_handler(callback: types.CallbackQuery):
    await _create_backup_and_refresh(callback, "logs")


async def create_nodes_backup_handler(callback: types.CallbackQuery):
    await _create_backup_and_refresh(callback, "nodes")


async def delete_backup_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if not _is_settings_allowed(user_id):
        await callback.answer(get_text("access_denied_generic", get_user_lang(user_id)), show_alert=True)
        return

    payload = callback.data.replace("delete_backup_", "", 1)
    parts = payload.split("_", 1)
    if len(parts) != 2:
        await callback.answer("Invalid backup identifier", show_alert=True)
        return

    backup_type, filename = parts
    cfg = BACKUP_TYPES.get(backup_type)
    if not cfg:
        await callback.answer("Unknown backup type", show_alert=True)
        return

    filepath = os.path.join(cfg["dir"], filename)
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
            await callback.answer(get_text("backup_deleted", get_user_lang(callback.from_user.id)))
        except Exception as e:
            await callback.answer(f"Error: {e}", show_alert=True)
    else:
        await callback.answer("File not found")
    await _show_backup_ui(callback, backup_type)


async def restore_backup_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if not _is_settings_allowed(user_id):
        await callback.answer(get_text("access_denied_generic", get_user_lang(user_id)), show_alert=True)
        return

    payload = callback.data.replace("restore_backup_", "", 1)
    parts = payload.split("_", 1)
    if len(parts) != 2:
        await callback.answer("Invalid backup identifier", show_alert=True)
        return

    backup_type, filename = parts
    cfg = BACKUP_TYPES.get(backup_type)
    if not cfg:
        await callback.answer("Unknown backup type", show_alert=True)
        return

    filepath = os.path.join(cfg["dir"], filename)
    if not os.path.exists(filepath):
        await callback.answer("File not found", show_alert=True)
        return

    lang = get_user_lang(user_id)
    try:
        await asyncio.to_thread(_restore_backup_file, backup_type, filepath)
        await callback.answer(get_text("backup_restored", lang), show_alert=True)
    except Exception as exc:
        logging.error(f"Failed to restore backup {filepath}: {exc}")
        await callback.answer(get_text("backup_restore_failed", lang), show_alert=True)

    await _show_backup_ui(callback, backup_type)

async def close_menu_handler(callback: types.CallbackQuery):
    await callback.message.delete()
