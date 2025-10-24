# /opt/tg-bot/modules/vless.py
import logging
import io
import qrcode
# from PIL import Image # Pillow импортирован в requirements, но Image не используется здесь
from aiogram import F, Dispatcher, types
from aiogram.types import KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter
from aiogram.exceptions import TelegramBadRequest

# --- ИЗМЕНЕНО: Импортируем i18n и config ---
from core.i18n import _, I18nFilter, get_user_lang
from core import config
# ----------------------------------------

# --- ИЗМЕНЕНО: Убираем send_access_denied_message, т.к. текст специфичен ---
from core.auth import is_allowed # , send_access_denied_message 
# ----------------------------------------------------------------------
from core.messaging import delete_previous_message
from core.shared_state import LAST_MESSAGE_IDS
from core.utils import convert_json_to_vless, escape_html
# --- ИЗМЕНЕНО: Импортируем get_main_reply_keyboard ---
from core.keyboards import get_back_keyboard, get_main_reply_keyboard
# ----------------------------------------------------

# --- ИЗМЕНЕНО: Используем ключ ---
BUTTON_KEY = "btn_vless"
# --------------------------------

class GenerateVlessStates(StatesGroup):
    waiting_for_file = State()
    waiting_for_name = State()

def get_button() -> KeyboardButton:
    # --- ИЗМЕНЕНО: Используем i18n ---
    return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))
    # --------------------------------

def register_handlers(dp: Dispatcher):
    # --- ИЗМЕНЕНО: Используем I18nFilter ---
    dp.message(I18nFilter(BUTTON_KEY))(generate_vless_handler)
    # --------------------------------------
    
    # FSM Handlers (остаются как есть)
    dp.message(StateFilter(GenerateVlessStates.waiting_for_file), F.document)(process_vless_file)
    dp.message(StateFilter(GenerateVlessStates.waiting_for_name), F.text)(process_vless_name)
    dp.message(StateFilter(GenerateVlessStates.waiting_for_file))(process_vless_file_invalid)
    dp.message(StateFilter(GenerateVlessStates.waiting_for_name))(process_vless_name_invalid)

async def generate_vless_handler(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    # --- ИЗМЕНЕНО: Получаем язык ---
    lang = get_user_lang(user_id)
    # ------------------------------
    command = "generate_vless" # Имя команды оставляем
    if not is_allowed(user_id, command):
        # --- ИЗМЕНЕНО: Используем i18n ---
        await message.bot.send_message(message.chat.id, _("access_denied_no_rights", lang))
        # --------------------------------
        return
    await delete_previous_message(user_id, command, message.chat.id, message.bot)
    
    # --- ИЗМЕНЕНО: Используем i18n ---
    cancel_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=_("btn_cancel", lang), callback_data="back_to_menu")]
    ])
    
    sent_message = await message.answer(
        _("vless_prompt_file", lang), 
        reply_markup=cancel_keyboard,
        parse_mode="HTML"
    )
    # --------------------------------
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
    await state.set_state(GenerateVlessStates.waiting_for_file)

async def process_vless_file(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    # --- ИЗМЕНЕНО: Получаем язык ---
    lang = get_user_lang(user_id)
    # ------------------------------
    command = "generate_vless"
    original_question_msg_id = None

    # Удаляем предыдущее сообщение с запросом файла
    if user_id in LAST_MESSAGE_IDS and command in LAST_MESSAGE_IDS[user_id]:
        original_question_msg_id = LAST_MESSAGE_IDS[user_id].pop(command)
        try:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=original_question_msg_id)
        except TelegramBadRequest:
            pass
    # Также удаляем сообщение пользователя с файлом
    try: await message.delete()
    except TelegramBadRequest: pass

    document = message.document
    if not document.file_name or not document.file_name.lower().endswith('.json'):
        # --- ИЗМЕНЕНО: Используем i18n ---
        cancel_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=_("btn_cancel", lang), callback_data="back_to_menu")]
        ])
        sent_message = await message.answer(
            _("vless_error_not_json", lang),
            parse_mode="HTML",
            reply_markup=cancel_keyboard
        )
        # --------------------------------
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
        # Остаемся в состоянии waiting_for_file
        return

    try:
        file = await message.bot.get_file(document.file_id)
        file_download_result = await message.bot.download_file(file.file_path)
        json_data = file_download_result.read().decode('utf-8')
        await state.update_data(json_data=json_data)

        # --- ИЗМЕНЕНО: Используем i18n ---
        cancel_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=_("btn_cancel", lang), callback_data="back_to_menu")]
        ])
        sent_message = await message.answer(
            _("vless_prompt_name", lang),
            parse_mode="HTML",
            reply_markup=cancel_keyboard
        )
        # --------------------------------
        LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
        await state.set_state(GenerateVlessStates.waiting_for_name)

    except Exception as e:
        logging.error(f"Ошибка при загрузке или чтении VLESS JSON: {e}")
        # --- ИЗМЕНЕНО: Используем i18n ---
        await message.answer(_("vless_error_file_processing", lang, error=e))
        # --------------------------------
        await state.clear()
        
async def process_vless_name(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    # --- ИЗМЕНЕНО: Получаем язык ---
    lang = get_user_lang(user_id)
    # ------------------------------
    command = "generate_vless"

    # Удаляем предыдущее сообщение с запросом имени
    if user_id in LAST_MESSAGE_IDS and command in LAST_MESSAGE_IDS[user_id]:
        try:
            await message.bot.delete_message(chat_id=message.chat.id, message_id=LAST_MESSAGE_IDS[user_id].pop(command))
        except TelegramBadRequest:
            pass
    # Также удаляем сообщение пользователя с именем
    try: await message.delete()
    except TelegramBadRequest: pass

    try:
        custom_name = message.text.strip()
        user_data = await state.get_data()
        json_data = user_data.get('json_data')

        if not json_data:
            # --- ИЗМЕНЕНО: Используем i18n ---
            await message.answer(
                _("vless_error_no_json_session", lang), 
                reply_markup=get_back_keyboard(lang, "back_to_menu") # Передаем lang
            )
            # --------------------------------
            await state.clear()
            return

        # convert_json_to_vless уже использует i18n для сообщения об ошибке
        vless_url = convert_json_to_vless(json_data, custom_name)

        if vless_url.startswith("⚠️"): # Проверяем на ошибку
             # --- ИЗМЕНЕНО: Передаем lang ---
            await message.answer(vless_url, reply_markup=get_back_keyboard(lang, "back_to_menu"))
             # --------------------------------
            await state.clear()
            return

        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
        qr.add_data(vless_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        img_buffer = io.BytesIO()
        img.save(img_buffer, format='PNG')
        img_buffer.seek(0)
        qr_file = BufferedInputFile(img_buffer.read(), filename="vless_qr.png")

        # --- ИЗМЕНЕНО: Используем i18n ---
        await message.bot.send_photo(
            chat_id=message.chat.id,
            photo=qr_file,
            caption=_("vless_success_caption", lang, name=escape_html(custom_name), url=escape_html(vless_url)),
            parse_mode="HTML"
        )
        
        # Возвращаем в главное меню
        sent_message = await message.answer(
            _("vless_menu_return", lang), 
            reply_markup=get_main_reply_keyboard(user_id, message.bot.buttons_map) # Передаем ID и карту
        )
        # --------------------------------
        LAST_MESSAGE_IDS.setdefault(user_id, {})["menu"] = sent_message.message_id # Сохраняем как сообщение меню

    except Exception as e:
        logging.error(f"Ошибка при генерации VLESS или QR: {e}")
        # --- ИЗМЕНЕНО: Используем i18n ---
        await message.answer(
            f"{_('error_unexpected', lang)}: {escape_html(str(e))}", 
            reply_markup=get_back_keyboard(lang, "back_to_menu") # Передаем lang
        )
        # --------------------------------
    finally:
        await state.clear()

async def process_vless_file_invalid(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    # --- ИЗМЕНЕНО: Получаем язык ---
    lang = get_user_lang(user_id)
    # ------------------------------
    command = "generate_vless"
    # --- ИЗМЕНЕНО: Используем i18n ---
    cancel_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=_("btn_cancel", lang), callback_data="back_to_menu")]
    ])
    sent_message = await message.reply(
        _("vless_error_not_file", lang),
        parse_mode="HTML",
        reply_markup=cancel_keyboard
    )
    # --------------------------------
    # Обновляем ID сообщения с ошибкой, чтобы его можно было удалить
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
    # Остаемся в состоянии waiting_for_file

async def process_vless_name_invalid(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    # --- ИЗМЕНЕНО: Получаем язык ---
    lang = get_user_lang(user_id)
    # ------------------------------
    command = "generate_vless"
    # --- ИЗМЕНЕНО: Используем i18n ---
    cancel_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=_("btn_cancel", lang), callback_data="back_to_menu")]
    ])
    sent_message = await message.reply(
        _("vless_error_not_text", lang),
        parse_mode="HTML",
        reply_markup=cancel_keyboard
    )
    # --------------------------------
    # Обновляем ID сообщения с ошибкой
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
    # Остаемся в состоянии waiting_for_name