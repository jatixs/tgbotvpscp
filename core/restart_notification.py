"""Independent restart-notification cleanup, safe to import in isolation."""

import logging
import os


async def notify_and_clear_restart_flag(bot, flag_file, language_for_user, translate, keyboard_factory):
    """Report a successful restart and always remove its marker.

    Backup directories are deliberately untouched, even if Telegram is unavailable.
    """
    if not os.path.exists(flag_file):
        return
    try:
        with open(flag_file, "r", encoding="utf-8") as marker:
            content = marker.read().strip()
        if ":" in content and content != "web:admin":
            chat_id, message_id = content.split(":", 1)
            lang = language_for_user(int(chat_id))
            await bot.edit_message_text(
                chat_id=int(chat_id),
                message_id=int(message_id),
                text=f"✅ {translate('utils_bot_restarted', lang)}",
                reply_markup=keyboard_factory(inline_keyboard=[]),
            )
    except Exception as exc:
        logging.error("Restart check error: %s", exc)
    finally:
        if os.path.exists(flag_file):
            os.remove(flag_file)
