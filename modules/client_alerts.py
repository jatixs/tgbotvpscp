"""
modules/client_alerts.py — Gateway Bot / Alert System (опциональный модуль).

Архитектура:
  • alert_bot  — второй Telegram-бот (шлюз для клиентов).
    Клиенты пишут ему → сообщения пересылаются администратору через main bot.
  • main bot   — получает тикеты; администратор управляет через inline-меню:
      ↳ кнопка «📣 Написать алерт» (cat_tools) → открывает панель управления
      ↳ «📣 Рассылка» → FSM рассылки
      ↳ «👥 Подписчики» → список подписчиков
      ↳ «💬 Ответить» под тикетом → FSM ответа

Активация: задать переменную окружения ALERT_BOT_TOKEN=<токен>.
Если токен не задан — модуль загружается, но alert_bot не стартует.

Хранилище подписчиков: config/alert_subscribers.json (простой JSON-файл).
"""

import asyncio
import json
import logging
import os
import time

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from core import config
from core.i18n import I18nFilter, get_user_lang

# ─── Константы ────────────────────────────────────────────────────────────────

ALERT_BOT_TOKEN: str | None = os.getenv("ALERT_BOT_TOKEN")

# Путь к JSON-файлу с ID подписчиков
SUBSCRIBERS_FILE = os.path.join(config.CONFIG_DIR, "alert_subscribers.json")

# Словарь для антифлуда: user_id -> timestamp
_user_last_message_time: dict[int, float] = {}

# ─── FSM States для main bot ──────────────────────────────────────────────────


class BroadcastStates(StatesGroup):
    """FSM: администратор делает рассылку всем подписчикам Alert Bot."""
    waiting_broadcast_message = State()


class ReplyStates(StatesGroup):
    """FSM: администратор отвечает конкретному пользователю Alert Bot."""
    waiting_reply_text = State()


# ─── Хранилище подписчиков ────────────────────────────────────────────────────

def _load_subscribers() -> dict[int, str]:
    """Загрузить словарь подписчиков из JSON-файла. Формат: {user_id: user_name}"""
    try:
        if os.path.exists(SUBSCRIBERS_FILE):
            with open(SUBSCRIBERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return {int(uid): f"ID {uid}" for uid in data}
                elif isinstance(data, dict):
                    return {int(k): v for k, v in data.items()}
    except Exception as e:
        logging.warning(f"[client_alerts] Не удалось загрузить подписчиков: {e}")
    return {}


def _save_subscribers(subscribers: dict[int, str]) -> None:
    """Сохранить словарь подписчиков в JSON-файл."""
    try:
        os.makedirs(os.path.dirname(SUBSCRIBERS_FILE), exist_ok=True)
        with open(SUBSCRIBERS_FILE, "w", encoding="utf-8") as f:
            json.dump(subscribers, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"[client_alerts] Не удалось сохранить подписчиков: {e}")


async def _add_subscriber(user_id: int, user_name: str) -> bool:
    """Добавить подписчика или обновить имя. Возвращает True если добавлен впервые."""
    subscribers = _load_subscribers()
    is_new = user_id not in subscribers
    if is_new or subscribers[user_id] != user_name:
        subscribers[user_id] = user_name
        _save_subscribers(subscribers)
    return is_new


# ─── Вспомогательные функции отправки ─────────────────────────────────────────

def _extract_message_payload(message: types.Message) -> dict:
    """
    Извлекает из сообщения сериализуемый payload для хранения в FSM state.
    Использует file_id — они глобальны в Telegram и работают между ботами.
    """
    caption = message.html_text if message.caption else ""
    text = message.html_text if message.text else ""
    
    if message.text:
        return {"type": "text", "text": text}
    elif message.photo:
        return {"type": "photo", "file_id": message.photo[-1].file_id, "caption": caption}
    elif message.video:
        return {"type": "video", "file_id": message.video.file_id, "caption": caption}
    elif message.audio:
        return {"type": "audio", "file_id": message.audio.file_id, "caption": caption}
    elif message.document:
        return {"type": "document", "file_id": message.document.file_id, "caption": caption}
    elif message.voice:
        return {"type": "voice", "file_id": message.voice.file_id, "caption": caption}
    elif message.video_note:
        return {"type": "video_note", "file_id": message.video_note.file_id}
    elif message.sticker:
        return {"type": "sticker", "file_id": message.sticker.file_id}
    elif message.animation:
        return {"type": "animation", "file_id": message.animation.file_id, "caption": caption}
    else:
        return {"type": "unsupported"}


async def _send_payload_via_alert_bot(chat_id: int, payload: dict, reply_to_message_id: int = None) -> None:
    """
    Отправляет payload через alert_bot в указанный chat_id.
    Если указан reply_to_message_id — отправляет ответом на конкретное сообщение.
    """
    if alert_bot is None:
        raise RuntimeError("Alert Bot не инициализирован")

    msg_type = payload.get("type", "unsupported")
    file_id = payload.get("file_id", "")
    text = payload.get("text", "")
    caption = payload.get("caption") or None

    if msg_type == "text":
        await alert_bot.send_message(chat_id, text, parse_mode="HTML", reply_to_message_id=reply_to_message_id)
    elif msg_type == "photo":
        await alert_bot.send_photo(chat_id, file_id, caption=caption, parse_mode="HTML", reply_to_message_id=reply_to_message_id)
    elif msg_type == "video":
        await alert_bot.send_video(chat_id, file_id, caption=caption, parse_mode="HTML", reply_to_message_id=reply_to_message_id)
    elif msg_type == "audio":
        await alert_bot.send_audio(chat_id, file_id, caption=caption, parse_mode="HTML", reply_to_message_id=reply_to_message_id)
    elif msg_type == "document":
        await alert_bot.send_document(chat_id, file_id, caption=caption, parse_mode="HTML", reply_to_message_id=reply_to_message_id)
    elif msg_type == "voice":
        await alert_bot.send_voice(chat_id, file_id, caption=caption, parse_mode="HTML", reply_to_message_id=reply_to_message_id)
    elif msg_type == "video_note":
        await alert_bot.send_video_note(chat_id, file_id, reply_to_message_id=reply_to_message_id)
    elif msg_type == "sticker":
        await alert_bot.send_sticker(chat_id, file_id, reply_to_message_id=reply_to_message_id)
    elif msg_type == "animation":
        await alert_bot.send_animation(chat_id, file_id, caption=caption, parse_mode="HTML", reply_to_message_id=reply_to_message_id)
    else:
        await alert_bot.send_message(chat_id, "⚠️ Неподдерживаемый тип сообщения.", reply_to_message_id=reply_to_message_id)


async def broadcast_system_alert(text: str) -> None:
    """
    Публичная функция для отправки системных алертов (например, падение ноды)
    всем подписчикам Gateway-бота.
    """
    if alert_bot is None:
        return
    subscribers = _load_subscribers()
    for uid in subscribers:
        try:
            await alert_bot.send_message(uid, text, parse_mode="HTML")
            await asyncio.sleep(0.05)
        except Exception as e:
            logging.warning(f"[client_alerts] Ошибка отправки системного алерта -> {uid}: {e}")


# ─── Alert Bot: инициализация ─────────────────────────────────────────────────

alert_bot: Bot | None = None
alert_dp: Dispatcher | None = None

if ALERT_BOT_TOKEN:
    try:
        alert_bot = Bot(token=ALERT_BOT_TOKEN)
        alert_dp = Dispatcher(storage=MemoryStorage())
        logging.info("[client_alerts] Alert Bot инициализирован успешно.")
    except Exception as _init_err:
        logging.error(f"[client_alerts] Ошибка инициализации Alert Bot: {_init_err}")
        alert_bot = None
        alert_dp = None
else:
    logging.info("[client_alerts] ALERT_BOT_TOKEN не задан — Alert Bot отключён.")


# ─── Inline-клавиатуры ────────────────────────────────────────────────────────

def _get_alert_panel_keyboard() -> InlineKeyboardMarkup:
    """
    Панель управления Alert Module для администратора.
    Открывается при нажатии кнопки «📣 Написать алерт» в главном боте.
    """
    subscribers = _load_subscribers()
    count_label = f"({len(subscribers)} чел.)" if subscribers else "(пусто)"
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
                    text="🔙 В главное меню",
                    callback_data="back_to_menu",
                ),
            ],
        ]
    )


def _get_reply_keyboard(client_user_id: int, client_message_id: int) -> InlineKeyboardMarkup:
    """Inline-кнопка 'Ответить' под входящим тикетом администратора."""
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


def _get_broadcast_confirm_keyboard() -> InlineKeyboardMarkup:
    """Подтверждение рассылки или отмена."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Отправить всем",
                    callback_data="alert_broadcast_confirm",
                ),
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="alert_fsm_cancel",
                ),
            ]
        ]
    )


def _get_cancel_keyboard() -> InlineKeyboardMarkup:
    """Кнопка отмены текущего FSM-действия."""
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


# ─── Alert Bot: обработчики ───────────────────────────────────────────────────

if alert_dp is not None:

    @alert_dp.message(Command("start"))
    async def alert_start_handler(message: types.Message) -> None:
        """
        Клиент нажимает /start в Alert Bot → подписывается на рассылки.
        """
        user_id = message.from_user.id
        user_name = message.from_user.full_name or f"ID {user_id}"
        is_new = await _add_subscriber(user_id, user_name)

        if is_new:
            await message.answer(
                "👋 Добро пожаловать!\n\n"
                "Вы подписались на уведомления от администратора.\n"
                "⚠️ <b>Внимание:</b> писать боту можно только <b>в ответ</b> на сообщения от администратора (используйте функцию Telegram «Ответить» / «Reply»).\n"
                "Обычные сообщения бот не принимает.",
                parse_mode="HTML"
            )
            logging.info(f"[client_alerts] Новый подписчик: {user_id} ({user_name})")
        else:
            await message.answer(
                "✅ Вы уже подписаны на уведомления.\n"
                "⚠️ Напоминаем: чтобы написать нам, используйте функцию «Ответить» на любое сообщение от администратора.",
                parse_mode="HTML"
            )

    @alert_dp.message()
    async def alert_message_handler(message: types.Message) -> None:
        """
        Любое сообщение клиента в Alert Bot → пересылается администратору через main bot.
        Администратор видит сообщение с inline-кнопкой 'Ответить'.
        """
        if alert_bot is None:
            return

        # Проверка, что это ответ на сообщение
        if not message.reply_to_message:
            await message.answer("⚠️ Ошибка: пожалуйста, используйте функцию <b>«Ответить»</b> (Reply) на сообщение от администратора, чтобы мы получили ваш ответ.", parse_mode="HTML")
            return

        reply = message.reply_to_message
        
        # Проверка ответа самому себе (BUG 5)
        if reply.from_user.id == message.from_user.id:
             await message.answer("⚠️ Ошибка: Вы ответили на своё собственное сообщение. Пожалуйста, ответьте на сообщение от администратора.")
             return

        # Проверка ответа на системное сообщение бота (BUG 6)
        if reply.from_user.id == alert_bot.id:
            if reply.text and (reply.text.startswith("⚠️") or reply.text.startswith("✅") or reply.text.startswith("👋") or reply.text.startswith("⏳")):
                 await message.answer("⚠️ Ошибка: Вы ответили на системное сообщение бота. Пожалуйста, ответьте на сообщение от администратора.")
                 return

        # Убеждаемся, что пользователь подписан
        user_id = message.from_user.id
        user_name = message.from_user.full_name or f"ID {user_id}"
        await _add_subscriber(user_id, user_name)

        # Антифлуд: максимум 1 сообщение в 3 секунды
        now = time.time()
        last_time = _user_last_message_time.get(user_id, 0)
        if now - last_time < 3.0:
            await message.answer("⏳ Пожалуйста, подождите несколько секунд перед отправкой следующего сообщения.")
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

        # Lazy import главного бота — избегаем циклических импортов
        try:
            import bot as main_bot_module
            main_bot_instance: Bot = main_bot_module.bot
        except ImportError:
            logging.error("[client_alerts] Не удалось импортировать главный бот.")
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
                # Медиа — форвардим оригинал
                await message.forward(config.ADMIN_USER_ID)

            await message.answer("✅ Ваше сообщение отправлено. Мы свяжемся с вами.")

        except Exception as e:
            logging.error(f"[client_alerts] Ошибка пересылки тикета: {e}")
            await message.answer("⚠️ Произошла ошибка при отправке. Попробуйте позже.")


# ─── Main Bot: панель управления (callback) ───────────────────────────────────

async def _alert_panel_open(message: types.Message, state: FSMContext) -> None:
    """
    Нажата кнопка «📣 Написать алерт» в главном боте → показываем панель управления.
    Доступно только администратору; обычным пользователям — заглушка.
    """
    user_id = message.from_user.id

    if user_id != config.ADMIN_USER_ID:
        # Обычным пользователям — информационное сообщение вместо ошибки
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
    Кнопка «📣 Рассылка» в панели → переходим в FSM ожидания сообщения для рассылки.
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
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer()
    
    text = (
        f"📣 <b>Рассылка</b>\n\n"
        f"Подписчиков: <b>{len(subscribers)}</b>\n\n"
        f"Отправьте сообщение для рассылки (текст, фото, видео и т.д.):"
    )
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=_get_cancel_keyboard())
    except Exception:
        pass


async def _cq_panel_subscribers(callback: types.CallbackQuery) -> None:
    """
    Кнопка «👥 Подписчики» → показываем список подписчиков прямо в inline-сообщении.
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
            f"📣 <b>Alert Module — Панель управления</b>\n\n"
            f"📭 Подписчиков пока нет.\n\n"
            f"Выберите действие:"
        )
        markup = _get_alert_panel_keyboard()
    else:
        PER_PAGE = 5
        items = list(subscribers.items())
        total_pages = max(1, (len(items) + PER_PAGE - 1) // PER_PAGE)
        if page > total_pages:
            page = total_pages
        if page < 1:
            page = 1
            
        start_idx = (page - 1) * PER_PAGE
        end_idx = start_idx + PER_PAGE
        current_items = items[start_idx:end_idx]
        
        ids_text = "\n".join(f"  • {name} (<code>{uid}</code>)" for uid, name in current_items)
        
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
    except Exception:
        pass


# ─── Main Bot: FSM — рассылка ─────────────────────────────────────────────────

async def _broadcast_message_received(
    message: types.Message, state: FSMContext
) -> None:
    """
    Получили сообщение для рассылки → сохраняем payload в FSM state,
    запрашиваем подтверждение.
    """
    payload = _extract_message_payload(message)
    subscribers = _load_subscribers()
    
    data = await state.get_data()
    panel_message_id = data.get("panel_message_id")
    await state.update_data(broadcast_payload=payload)
    
    text = (
        f"⚠️ <b>Подтверждение рассылки</b>\n\n"
        f"Это сообщение будет отправлено <b>{len(subscribers)}</b> подписчикам.\n"
        f"Продолжить?"
    )

    try:
        await message.delete()
    except Exception:
        pass

    try:
        import bot as main_bot_module
        main_bot_instance: Bot = main_bot_module.bot
        await main_bot_instance.edit_message_text(
            chat_id=message.chat.id,
            message_id=panel_message_id,
            text=text,
            parse_mode="HTML",
            reply_markup=_get_broadcast_confirm_keyboard(),
        )
    except Exception:
        await message.answer(text, parse_mode="HTML", reply_markup=_get_broadcast_confirm_keyboard())


async def _broadcast_confirm(
    callback: types.CallbackQuery, state: FSMContext
) -> None:
    """Администратор подтвердил рассылку."""
    if callback.from_user.id != config.ADMIN_USER_ID:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return

    data = await state.get_data()
    payload = data.get("broadcast_payload")
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
    await callback.message.edit_reply_markup(reply_markup=None)

    sent_ok = 0
    sent_fail = 0

    for uid in subscribers:
        try:
            await _send_payload_via_alert_bot(uid, payload)
            sent_ok += 1
            await asyncio.sleep(0.05)  # rate limit guard
        except Exception as e:
            logging.warning(f"[client_alerts] Рассылка → {uid}: {e}")
            sent_fail += 1

    result_text = (
        f"✅ <b>Рассылка завершена</b>\n\n"
        f"📤 Успешно: <b>{sent_ok}</b>\n"
        f"❌ Ошибок: <b>{sent_fail}</b>\n\n"
        f"Выберите действие:"
    )
    try:
        await callback.message.edit_text(result_text, parse_mode="HTML", reply_markup=_get_alert_panel_keyboard())
    except Exception:
        pass


# ─── Main Bot: FSM — ответ на тикет ──────────────────────────────────────────

async def _alert_reply_callback(
    callback: types.CallbackQuery, state: FSMContext
) -> None:
    """
    Кнопка «💬 Ответить» под входящим тикетом → FSM ReplyStates.
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
    except Exception:
        pass


async def _reply_text_received(message: types.Message, state: FSMContext) -> None:
    """
    Получили ответ от администратора → пересылаем клиенту через alert_bot
    используя file_id / текст напрямую (без copy_message).
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

    payload = _extract_message_payload(message)
    
    try:
        await message.delete()
    except Exception:
        pass

    try:
        await _send_payload_via_alert_bot(client_user_id, payload, reply_to_message_id=client_message_id)
        logging.info(f"[client_alerts] Ответ отправлен клиенту {client_user_id}.")
        text = f"✅ <b>Ответ отправлен</b> клиенту <code>{client_user_id}</code>."
    except Exception as e:
        logging.error(f"[client_alerts] Ошибка ответа клиенту {client_user_id}: {e}")
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


# ─── Main Bot: общая отмена FSM через кнопку ─────────────────────────────────

async def _cq_fsm_cancel(callback: types.CallbackQuery, state: FSMContext) -> None:
    """
    Кнопка «❌ Отмена» во время любого FSM-ввода (рассылка, ответ).
    Сбрасывает состояние и возвращает панель управления.
    """
    await state.clear()
    subscribers = _load_subscribers()
    text = (
        f"❌ Действие отменено.\n\n"
        f"📣 <b>Alert Module — Панель управления</b>\n\n"
        f"👥 Подписчиков: <b>{len(subscribers)}</b>\n"
        f"🤖 Alert Bot: <b>{'активен' if alert_bot else 'не активен'}</b>\n\n"
        f"Выберите действие:"
    )
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=_get_alert_panel_keyboard())
    except Exception:
        pass
    await callback.answer("Отменено.")


# ─── register_handlers + start_background_tasks ───────────────────────────────

def register_handlers(dp: Dispatcher) -> None:
    """
    Регистрируем обработчики в ГЛАВНОМ боте.
    Вызывается оркестратором при загрузке модуля (tier=ALWAYS_ON).
    """
    if not ALERT_BOT_TOKEN:
        logging.info(
            "[client_alerts] ALERT_BOT_TOKEN не задан. "
            "Хендлеры Alert Module не зарегистрированы."
        )
        return

    # Кнопка «📣 Написать алерт» → панель управления
    dp.message(I18nFilter("btn_client_alerts"))(_alert_panel_open)

    # Callback: «📣 Рассылка» в панели
    dp.callback_query(F.data == "alert_panel_broadcast")(_cq_panel_broadcast)

    # Callback: «👥 Подписчики» в панели
    dp.callback_query(F.data == "alert_panel_subscribers")(_cq_panel_subscribers)
    dp.callback_query(F.data.startswith("alert_panel_subscribers_page_"))(_cq_panel_subscribers)

    # FSM: получили сообщение для рассылки
    dp.message(BroadcastStates.waiting_broadcast_message)(_broadcast_message_received)

    # Callbacks подтверждения рассылки
    dp.callback_query(F.data == "alert_broadcast_confirm")(_broadcast_confirm)

    # Callback «💬 Ответить» под входящим тикетом
    dp.callback_query(F.data.startswith("alert_reply_"))(_alert_reply_callback)

    # FSM: получили ответное сообщение администратора
    dp.message(ReplyStates.waiting_reply_text)(_reply_text_received)

    # Кнопка «❌ Отмена» в любом FSM-режиме
    dp.callback_query(F.data == "alert_fsm_cancel")(_cq_fsm_cancel)

    logging.info(
        "[client_alerts] Хендлеры Alert Module зарегистрированы в главном боте."
    )


def start_background_tasks(bot: Bot) -> list[asyncio.Task]:
    """
    Запускает поллинг Alert Bot как фоновую asyncio-задачу.
    Вызывается оркестратором для ALWAYS_ON модулей.

    Args:
        bot: Экземпляр ГЛАВНОГО бота (сигнатура требуется оркестратором).

    Returns:
        Список asyncio.Task. Пустой если ALERT_BOT_TOKEN не задан.
    """
    if alert_bot is None or alert_dp is None:
        logging.info("[client_alerts] Alert Bot не запущен (токен не задан).")
        return []

    async def _run_alert_polling() -> None:
        """Запускает поллинг Alert Bot с graceful shutdown."""
        logging.info("[client_alerts] Запуск поллинга Alert Bot...")
        try:
            await alert_bot.delete_webhook(drop_pending_updates=True)
            await alert_dp.start_polling(
                alert_bot,
                allowed_updates=alert_dp.resolve_used_update_types(),
            )
        except asyncio.CancelledError:
            logging.info("[client_alerts] Поллинг Alert Bot остановлен.")
        except Exception as e:
            logging.error(f"[client_alerts] Критическая ошибка Alert Bot: {e}", exc_info=True)
        finally:
            try:
                session = getattr(alert_bot, "session", None)
                if session:
                    await session.close()
            except Exception:
                pass
            logging.info("[client_alerts] Alert Bot завершён.")

    task = asyncio.create_task(_run_alert_polling(), name="AlertBotPolling")
    logging.info("[client_alerts] Фоновая задача Alert Bot создана.")
    return [task]
