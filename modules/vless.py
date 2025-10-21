# /opt/tg-bot/modules/vless.py
import logging
import io
import qrcode
from PIL import Image
from aiogram import F, Dispatcher, types
from aiogram.types import KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter
from aiogram.exceptions import TelegramBadRequest

from core.auth import is_allowed
from core.messaging import delete_previous_message
from core.shared_state import LAST_MESSAGE_IDS
from core.utils import convert_json_to_vless, escape_html
from core.keyboards import get_back_keyboard, get_main_reply_keyboard

BUTTON_TEXT = "🔗 VLESS-ссылка"


class GenerateVlessStates(StatesGroup):
    waiting_for_file = State()
    waiting_for_name = State()


def get_button() -> KeyboardButton:
    return KeyboardButton(text=BUTTON_TEXT)


def register_handlers(dp: Dispatcher):
    dp.message(F.text == BUTTON_TEXT)(generate_vless_handler)

    # FSM Handlers
    dp.message(
        StateFilter(
            GenerateVlessStates.waiting_for_file),
        F.document)(process_vless_file)
    dp.message(
        StateFilter(
            GenerateVlessStates.waiting_for_name),
        F.text)(process_vless_name)
    dp.message(StateFilter(GenerateVlessStates.waiting_for_file))(
        process_vless_file_invalid)
    dp.message(StateFilter(GenerateVlessStates.waiting_for_name))(
        process_vless_name_invalid)


async def generate_vless_handler(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    command = "generate_vless"
    if not is_allowed(user_id, command):
        await message.bot.send_message(message.chat.id, "⛔ У вас нет прав для выполнения этой команды.")
        return
    await delete_previous_message(user_id, command, message.chat.id, message.bot)

    cancel_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить", callback_data="back_to_menu")]
    ])

    sent_message = await message.answer(
        "📤 <b>Отправьте файл конфигурации Xray (JSON)</b>\n\n<i>Важно: файл должен содержать рабочую конфигурацию outbound с Reality.</i>",
        reply_markup=cancel_keyboard,
        parse_mode="HTML"
    )
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
    await state.set_state(GenerateVlessStates.waiting_for_file)


async def process_vless_file(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    command = "generate_vless"
    original_question_msg_id = None

    if user_id in LAST_MESSAGE_IDS and command in LAST_MESSAGE_IDS[user_id]:
        original_question_msg_id = LAST_MESSAGE_IDS[user_id].pop(command)
        try:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=original_question_msg_id)
        except TelegramBadRequest:
            pass

    document = message.document
    if not document.file_name or not document.file_name.lower().endswith('.json'):
        cancel_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить", callback_data="back_to_menu")]
        ])
        sent_message = await message.answer(
            "⛔ <b>Ошибка:</b> Файл должен быть формата <code>.json</code>.\n\nПопробуйте отправить файл еще раз.",
            parse_mode="HTML",
            reply_markup=cancel_keyboard
        )
        LAST_MESSAGE_IDS.setdefault(
            user_id, {})[command] = sent_message.message_id
        return

    try:
        file = await message.bot.get_file(document.file_id)
        file_download_result = await message.bot.download_file(file.file_path)
        json_data = file_download_result.read().decode('utf-8')
        await state.update_data(json_data=json_data)

        cancel_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить", callback_data="back_to_menu")]
        ])
        sent_message = await message.answer(
            "✅ Файл JSON получен.\n\n"
            "Теперь <b>введите имя</b> для этой VLESS-ссылки (например, 'My_Server_1'):",
            parse_mode="HTML",
            reply_markup=cancel_keyboard
        )
        LAST_MESSAGE_IDS.setdefault(
            user_id, {})[command] = sent_message.message_id
        await state.set_state(GenerateVlessStates.waiting_for_name)

    except Exception as e:
        logging.error(f"Ошибка при загрузке или чтении VLESS JSON: {e}")
        await message.answer(f"⚠️ Произошла ошибка при обработке файла: {e}")
        await state.clear()


async def process_vless_name(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    command = "generate_vless"

    if user_id in LAST_MESSAGE_IDS and command in LAST_MESSAGE_IDS[user_id]:
        try:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=LAST_MESSAGE_IDS[user_id].pop(command))
        except TelegramBadRequest:
            pass

    try:
        custom_name = message.text.strip()
        user_data = await state.get_data()
        json_data = user_data.get('json_data')

        if not json_data:
            await message.answer("⚠️ Ошибка: Данные JSON не найдены в сессии. Попробуйте сначала.", reply_markup=get_back_keyboard("back_to_menu"))
            await state.clear()
            return

        vless_url = convert_json_to_vless(json_data, custom_name)

        if vless_url.startswith("⚠️"):
            await message.answer(vless_url, reply_markup=get_back_keyboard("back_to_menu"))
            await state.clear()
            return

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4)
        qr.add_data(vless_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        img_buffer = io.BytesIO()
        img.save(img_buffer, format='PNG')
        img_buffer.seek(0)
        qr_file = BufferedInputFile(img_buffer.read(), filename="vless_qr.png")

        await message.bot.send_photo(
            chat_id=message.chat.id,
            photo=qr_file,
            caption=f"✅ Ваша VLESS-ссылка с именем '<b>{escape_html(custom_name)}</b>' готова:\n\n"
                    f"<code>{escape_html(vless_url)}</code>",
            parse_mode="HTML"
        )

        sent_message = await message.answer("🏠 Возврат в главное меню.", reply_markup=get_main_reply_keyboard(user_id, message.bot.buttons_map))
        LAST_MESSAGE_IDS.setdefault(
            user_id, {})["menu"] = sent_message.message_id

    except Exception as e:
        logging.error(f"Ошибка при генерации VLESS или QR: {e}")
        await message.answer(f"⚠️ Произошла критическая ошибка: {e}", reply_markup=get_back_keyboard("back_to_menu"))
    finally:
        await state.clear()


async def process_vless_file_invalid(
        message: types.Message,
        state: FSMContext):
    cancel_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить", callback_data="back_to_menu")]
    ])
    sent_message = await message.reply(
        "⛔ Пожалуйста, отправьте <b>документ</b> (файл), а не текст.",
        parse_mode="HTML",
        reply_markup=cancel_keyboard
    )
    LAST_MESSAGE_IDS.setdefault(message.from_user.id, {})[
        "generate_vless"] = sent_message.message_id


async def process_vless_name_invalid(
        message: types.Message,
        state: FSMContext):
    cancel_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить", callback_data="back_to_menu")]
    ])
    sent_message = await message.reply(
        "⛔ Пожалуйста, отправьте <b>текстовое имя</b>.",
        parse_mode="HTML",
        reply_markup=cancel_keyboard
    )
    LAST_MESSAGE_IDS.setdefault(message.from_user.id, {})[
        "generate_vless"] = sent_message.message_id
