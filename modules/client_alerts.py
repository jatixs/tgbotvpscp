"""
modules/client_alerts.py — Gateway Bot / Alert System (опциональный модуль).

Архитектура:
  • alert_bot  — второй Telegram-бот (шлюз для клиентов).
    Клиенты пишут ему → сообщения пересылаются администратору через main bot.
  • main bot   — получает тикеты, администратор отвечает или делает рассылку.

Активация: задать переменную окружения ALERT_BOT_TOKEN=<токен>.
Если токен не задан — модуль загружается, но alert_bot не стартует.

Хранилище подписчиков: config/alert_subscribers.json (простой JSON-файл).
"""

import asyncio
import json
import logging
import os

from aiogram import Bot, Dispatcher, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from core import config
from core.i18n import I18nFilter, _, get_user_lang

# ─── Константы ────────────────────────────────────────────────────────────────

ALERT_BOT_TOKEN: str | None = os.getenv("ALERT_BOT_TOKEN")

# Путь к JSON-файлу с ID подписчиков
SUBSCRIBERS_FILE = os.path.join(config.CONFIG_DIR, "alert_subscribers.json")

# ─── FSM States для main bot ──────────────────────────────────────────────────


class BroadcastStates(StatesGroup):
    """FSM: администратор делает рассылку всем подписчикам Alert Bot."""
    waiting_broadcast_message = State()


class ReplyStates(StatesGroup):
    """FSM: администратор отвечает конкретному пользователю Alert Bot."""
    waiting_reply_text = State()


# ─── Хранилище подписчиков ────────────────────────────────────────────────────

def _load_subscribers() -> list[int]:
    """Загрузить список ID подписчиков из JSON-файла."""
    try:
        if os.path.exists(SUBSCRIBERS_FILE):
            with open(SUBSCRIBERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return [int(uid) for uid in data]
    except Exception as e:
        logging.warning(f"[client_alerts] Не удалось загрузить подписчиков: {e}")
    return []


def _save_subscribers(subscribers: list[int]) -> None:
    """Сохранить список ID подписчиков в JSON-файл."""
    try:
        os.makedirs(os.path.dirname(SUBSCRIBERS_FILE), exist_ok=True)
        with open(SUBSCRIBERS_FILE, "w", encoding="utf-8") as f:
            json.dump(list(set(subscribers)), f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"[client_alerts] Не удалось сохранить подписчиков: {e}")


async def _add_subscriber(user_id: int) -> bool:
    """Добавить подписчика. Возвращает True если добавлен впервые."""
    subscribers = _load_subscribers()
    if user_id not in subscribers:
        subscribers.append(user_id)
        _save_subscribers(subscribers)
        return True
    return False


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


# ─── Вспомогательные клавиатуры ───────────────────────────────────────────────

def _get_reply_keyboard(client_user_id: int) -> InlineKeyboardMarkup:
    """Inline-клавиатура с кнопкой 'Ғотовить' для главного бота."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💬 Ответить",
                    callback_data=f"alert_reply_{client_user_id}",
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
                    text="✅ Подтвердить рассылку",
                    callback_data="alert_broadcast_confirm",
                ),
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="alert_broadcast_cancel",
                ),
            ]
        ]
    )


def _get_alert_admin_keyboard(subscribers_count: int) -> InlineKeyboardMarkup:
    """Главное инлайн-меню Alert-модуля для администратора."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"📢 Рассылка",
                    callback_data="alert_start_broadcast",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=f"👥 Подписчики: {subscribers_count}",
                    callback_data="alert_show_subscribers",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔙 Назад в меню",
                    callback_data="back_to_menu",
                ),
            ],
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
        is_new = await _add_subscriber(user_id)
        user_name = message.from_user.full_name or f"ID {user_id}"

        if is_new:
            await message.answer(
                "👋 Добро пожаловать!\n\n"
                "Вы подписались на уведомления от администратора.\n"
                "Вы можете написать нам любое сообщение — мы обязательно ответим."
            )
            logging.info(f"[client_alerts] Новый подписчик: {user_id} ({user_name})")
        else:
            await message.answer(
                "✅ Вы уже подписаны на уведомления.\n"
                "Напишите нам любое сообщение — администратор ответит вам."
            )

    @alert_dp.message()
    async def alert_message_handler(message: types.Message) -> None:
        """
        Любое сообщение клиента в Alert Bot → пересылается администратору через main bot.
        Администратор видит сообщение с inline-кнопкой 'Ответить'.
        """
        if alert_bot is None:
            return

        # Убеждаемся, что пользователь подписан
        await _add_subscriber(message.from_user.id)

        user_id = message.from_user.id
        user_name = message.from_user.full_name or f"ID {user_id}"
        username_str = (
           # ─── Main Bot: обработчики (регистрируются в register_handlers) ────────────────

async def _alert_menu_handler(message: types.Message, state: FSMContext) -> None:
    """
    Нажатие кнопки "📣 Написать алерт" → показываем админ-панель с inline-кнопками.
    """
    user_id = message.from_user.id
    if user_id != config.ADMIN_USER_ID:
        return

    await state.clear()
    subscribers = _load_subscribers()
    await message.answer(
        f"📣 <b>Alert Модуль</b>\n\n"
        f"👥 Подписчиков: <b>{len(subscribers)}</b>\n"
        f"🤖 Alert Bot: <b>{'\u0430ктивен' if alert_bot else 'не активен'}</b>\n\n"
        f"Выберите действие:",
        parse_mode="HTML",
        reply_markup=_get_alert_admin_keyboard(len(subscribers)),
    )


async def _alert_start_broadcast_callback(
    callback: types.CallbackQuery, state: FSMContext
) -> None:
    """
    Нажатие "📢 Рассылка" → входим в FSM BroadcastStates.
    """
    if callback.from_user.id != config.ADMIN_USER_ID:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return

    subscribers = _load_subscribers()
    if not subscribers:
        await callback.answer("💭 Нет подписчиков.", show_alert=True)
        return

    if alert_bot is None:
        await callback.answer("⚠️ Alert Bot не активен.", show_alert=True)
        return

    await state.set_state(BroadcastStates.waiting_broadcast_message)
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"📣 <b>Рассылка</b>\n\n"
        f"Подписчиков: <b>{len(subscribers)}</b>\n\n"
        f"Отправьте сообщение для рассылки (текст, фото, видео и т.д.).\n"
        f"Для отмены нажмите /cancel",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="❌ Отмена", callback_data="alert_broadcast_cancel")
            ]]
        ),
    )


async def _alert_show_subscribers_callback(
    callback: types.CallbackQuery,
) -> None:
    """
    Нажатие "👥 Подписчики" → показываем список ID с кнопкой "Назад".
    """
    if callback.from_user.id != config.ADMIN_USER_ID:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return

    subscribers = _load_subscribers()
    await callback.answer()

    if not subscribers:
        await callback.message.answer(
            "💭 <b>Список подписчиков Alert Bot пуст.</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(text="← Назад", callback_data="alert_back_to_menu")
                ]]
            ),
        )
        return

    ids_text = "\n".join(f"  • <code>{uid}</code>" for uid in subscribers[:50])
    suffix = (
        f"\n  <i>...и ещё {len(subscribers) - 50}</i>"
        if len(subscribers) > 50
        else ""
    )

    await callback.message.answer(
        f"👥 <b>Подписчики Alert Bot</b>\n\n"
        f"Всего: <b>{len(subscribers)}</b>\n\n"
        f"{ids_text}{suffix}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="← Назад", callback_data="alert_back_to_menu")
            ]]
        ),
    )�кой «Ответить»
            await main_bot_instance.send_message(
                config.ADMIN_USER_ID,
                ticket_header,
                parse_mode="HTML",
                reply_markup=_get_reply_keyboard(user_id),
            )
            # Пересылаем оригинальное сообщение (если это текст — копируем, иначе forward)
            if message.text:
                await main_bot_instance.send_message(
                    config.ADMIN_USER_ID,
                    f"<i>{message.text}</i>",
                    parse_mode="HTML",
                )
            else:
                # Для медиа используем forward
                await message.forward(config.ADMIN_USER_ID)

            # Подтверждаем клиенту получение
            await message.answer("✅ Ваше сообщение отправлено. Мы свяжемся с вами.")

        except Exception as e:
            logging.error(
                f"[client_alerts] Ошибка пересылки тикета администратору: {e}"
            )
            await message.answer(
                "⚠️ Произошла ошибка при отправке. Попробуйте позже."
            )


# ─── Main Bot: обработчики (регистрируются в register_handlers) ────────────────

async def _cmd_broadcast(message: types.Message, state: FSMContext) -> None:
    """
    /broadcast — начало рассылки всем подписчикам Alert Bot (только ADMIN_USER_ID).
    """
    user_id = message.from_user.id

    if user_id != config.ADMIN_USER_ID:
        await message.answer("⛔ Нет доступа.")
        return

    subscribers = _load_subscribers()
    if not subscribers:
        await message.answer(
            "📭 <b>Список подписчиков пуст.</b>\n"
            "Нет ни одного подписчика Alert Bot.",
            parse_mode="HTML",
        )
        return

    await state.set_state(BroadcastStates.waiting_broadcast_message)
    await message.answer(
        f"📣 <b>Рассылка</b>\n\n"
        f"Подписчиков: <b>{len(subscribers)}</b>\n\n"
        f"Отправьте сообщение для рассылки (текст, фото, видео и т.д.).\n"
        f"Для отмены отправьте /cancel",
        parse_mode="HTML",
    )


async def _broadcast_message_received(
    message: types.Message, state: FSMContext
) -> None:
    """
    Получили сообщение для рассылки — запрашиваем подтверждение перед отправкой.
    """
    if message.text and message.text.strip() == "/cancel":
        await state.clear()
        await message.answer("❌ Рассылка отменена.")
        return

    # Сохраняем message_id и chat_id для последующего copy_message
    await state.update_data(
        broadcast_chat_id=message.chat.id,
        broadcast_message_id=message.message_id,
    )

    subscribers = _load_subscribers()
    await message.answer(
        f"⚠️ <b>Подтверждение рассылки</b>\n\n"
        f"Это сообщение будет отправлено <b>{len(subscribers)}</b> подписчикам.\n"
        f"Продолжить?",
        parse_mode="HTML",
        reply_markup=_get_broadcast_confirm_keyboard(),
    )


async def _broadcast_confirm(
    callback: types.CallbackQuery, state: FSMContext
) -> None:
    """Администратор подтвердил рассылку — отправляем всем подписчикам."""
    if callback.from_user.id != config.ADMIN_USER_ID:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return

    data = await state.get_data()
    src_chat_id = data.get("broadcast_chat_id")
    src_msg_id = data.get("broadcast_message_id")
    await state.clear()

    if not src_chat_id or not src_msg_id:
        await callback.answer("⚠️ Ошибка: данные рассылки утеряны.", show_alert=True)
        return

    subscribers = _load_subscribers()
    if not subscribers:
        await callback.answer("📭 Нет подписчиков.", show_alert=True)
        return

    if alert_bot is None:
        await callback.answer("⚠️ Alert Bot не активен.", show_alert=True)
        return

    await callback.answer("📤 Рассылка запущена...")
    await callback.message.edit_reply_markup(reply_markup=None)

    sent_ok = 0
    sent_fail = 0

    for uid in subscribers:
        try:
            await alert_bot.copy_message(
                chat_id=uid,
                from_chat_id=src_chat_id,
                message_id=src_msg_id,
            )
            sent_ok += 1
            # Небольшая задержка для соблюдения Telegram rate limits
            await asyncio.sleep(0.05)
        except Exception as e:
            logging.warning(
                f"[client_alerts] Не удалось отправить рассылку {uid}: {e}"
            )
            sent_fail += 1

    await callback.message.answer(
        f"✅ <b>Рассылка завершена</b>\n\n"
        f"📤 Успешно: <b>{sent_ok}</b>\n"
        f"❌ Ошибок: <b>{sent_fail}</b>",
        parse_mode="HTML",
    )


async def _broadcast_cancel(
    callback: types.CallbackQuery, state: FSMContext
) -> None:
    """Администратор отменил рассылку."""
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("❌ Рассылка отменена.")
    await callback.answer()


async def _alert_reply_callback(
    callback: types.CallbackQuery, state: FSMContext
) -> None:
    """
    Администратор нажал 'Ответить' под тикетом → входим в FSM ReplyStates.
    Сохраняем ID клиента и ждём ответного сообщения.
 # ─── register_handlers + start_background_tasks ────────────────────────────────

def register_handlers(dp: Dispatcher) -> None:
    """
    Регистрируем обработчики в ГЛАВНОМ боте:
      - Кнопка "📣 Написать алерт" → открывает inline-меню
      - "📢 Рассылка" callback → FSM рассылки
      - "👥 Подписчики" callback → список ID
      - callback 'alert_reply_{id}' + FSM ответа
    Вызывается оркестратором при загрузке модуля (tier=ALWAYS_ON).
    """
    if not ALERT_BOT_TOKEN:
        logging.info(
            "[client_alerts] ALERT_BOT_TOKEN не задан. "
            "Хендлеры Alert Module не зарегистрированы."
        )
        return

    # Кнопка "📣 Написать алерт" / "📣 Write Alert" → открывает админ-панель
    dp.message(I18nFilter("btn_client_alerts"))(_alert_menu_handler)

    # Callback "📢 Рассылка" → входим в FSM
    dp.callback_query(F.data == "alert_start_broadcast")(_alert_start_broadcast_callback)

    # Callback "👥 Подписчики" → показываем список
    dp.callback_query(F.data == "alert_show_subscribers")(_alert_show_subscribers_callback)

    # Callback "Назад" внутри модуля
    dp.callback_query(F.data == "alert_back_to_menu")(_alert_back_to_menu_callback)

    # FSM: ввод текста рассылки
    dp.message(BroadcastStates.waiting_broadcast_message)(_broadcast_message_received)

    # Callbacks подтверждения/отмены рассылки
    dp.callback_query(F.data == "alert_broadcast_confirm")(_broadcast_confirm)
    dp.callback_query(F.data == "alert_broadcast_cancel")(_broadcast_cancel)

    # Callback «Ответить» под тикетом
    dp.callback_query(F.data.startswith("alert_reply_"))(_alert_reply_callback)

    # FSM: ввод ответного сообщения
    dp.message(ReplyStates.waiting_reply_text)(_reply_text_received)

    logging.info(
        "[client_alerts] Хендлеры Alert Module зарегистрированы (с inline-меню)."
    )�остоянии FSM.")
        return

    if alert_bot is None:
        await message.answer("⚠️ Alert Bot не активен — ответ невозможен.")
        return

    try:
        # copy_message поддерживает медиа, стикеры и т.д.
        await alert_bot.copy_message(
            chat_id=client_user_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
        await message.answer(
            f"✅ <b>Ответ отправлен</b> клиенту <code>{client_user_id}</code>.",
            parse_mode="HTML",
        )
        logging.info(
            f"[client_alerts] Администратор ответил клиенту {client_user_id}."
        )
    except Exception as e:
        logging.error(
            f"[client_alerts] Не удалось отправить ответ клиенту {client_user_id}: {e}"
        )
        await message.answer(
            f"❌ Ошибка отправки клиенту <code>{client_user_id}</code>:\n{e}",
            parse_mode="HTML",
        )


async def _alert_subscribers_cmd(message: types.Message) -> None:
    """
    /alert_subscribers — статистика по подписчикам (только для администратора).
    """
    if message.from_user.id != config.ADMIN_USER_ID:
        return

    subscribers = _load_subscribers()

    if not subscribers:
        await message.answer(
            "📭 <b>Список подписчиков Alert Bot пуст.</b>",
            parse_mode="HTML",
        )
        return

    ids_text = "\n".join(f"  • <code>{uid}</code>" for uid in subscribers[:50])
    suffix = (
        f"\n  <i>...и ещё {len(subscribers) - 50}</i>"
        if len(subscribers) > 50
        else ""
    )

    await message.answer(
        f"👥 <b>Подписчики Alert Bot</b>\n\n"
        f"Всего: <b>{len(subscribers)}</b>\n\n"
        f"{ids_text}{suffix}",
        parse_mode="HTML",
    )


# ─── register_handlers + start_background_tasks ───────────────────────────────

def register_handlers(dp: Dispatcher) -> None:
    """
    Регистрируем обработчики в ГЛАВНОМ боте:
      - /broadcast + FSM рассылки
      - callback 'alert_reply_{id}' + FSM ответа
      - /alert_subscribers — статистика
    Вызывается оркестратором при загрузке модуля (tier=ALWAYS_ON).
    """
    if not ALERT_BOT_TOKEN:
        # Модуль загружен, но Alert Bot не активен — хендлеры не нужны
        logging.info(
            "[client_alerts] ALERT_BOT_TOKEN не задан. "
            "Хендлеры рассылки и тикетов не зарегистрированы."
        )
        return

    # /broadcast — начало рассылки
    dp.message(Command("broadcast"))(_cmd_broadcast)

    # FSM: ввод текста рассылки (перехватываем любое сообщение в этом состоянии)
    dp.message(BroadcastStates.waiting_broadcast_message)(_broadcast_message_received)

    # Callbacks подтверждения/отмены рассылки
    dp.callback_query(F.data == "alert_broadcast_confirm")(_broadcast_confirm)
    dp.callback_query(F.data == "alert_broadcast_cancel")(_broadcast_cancel)

    # Callback «Ответить» под тикетом
    dp.callback_query(F.data.startswith("alert_reply_"))(_alert_reply_callback)

    # FSM: ввод ответного сообщения
    dp.message(ReplyStates.waiting_reply_text)(_reply_text_received)

    # /alert_subscribers — статистика
    dp.message(Command("alert_subscribers"))(_alert_subscribers_cmd)

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
        logging.info(
            "[client_alerts] Alert Bot не запущен (ALERT_BOT_TOKEN не задан)."
        )
        return []

    async def _run_alert_polling() -> None:
        """Запускает поллинг Alert Bot с обработкой ошибок."""
        logging.info("[client_alerts] Запуск поллинга Alert Bot...")
        try:
            await alert_bot.delete_webhook(drop_pending_updates=True)
            await alert_dp.start_polling(
                alert_bot,
                allowed_updates=alert_dp.resolve_used_update_types(),
            )
        except asyncio.CancelledError:
            logging.info(
                "[client_alerts] Поллинг Alert Bot остановлен (CancelledError)."
            )
        except Exception as e:
            logging.error(
                f"[client_alerts] Критическая ошибка Alert Bot: {e}", exc_info=True
            )
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
