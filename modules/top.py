import asyncio
from aiogram import Dispatcher, types
from aiogram.types import KeyboardButton
from core.i18n import _, I18nFilter, get_user_lang
from core import config
from core.auth import is_allowed, send_access_denied_message
from core.messaging import delete_previous_message
from core.shared_state import LAST_MESSAGE_IDS
from core.utils import escape_html

BUTTON_KEY = "btn_top"


def get_button() -> KeyboardButton:
    return KeyboardButton(text=_(BUTTON_KEY, config.DEFAULT_LANGUAGE))


def register_handlers(dp: Dispatcher):
    dp.message(I18nFilter(BUTTON_KEY))(top_handler)


async def top_handler(message: types.Message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    lang = get_user_lang(user_id)
    command = "top"
    if not is_allowed(user_id, command):
        await send_access_denied_message(message.bot, user_id, chat_id, command)
        return
    await message.bot.send_chat_action(chat_id=chat_id, action="typing")
    await delete_previous_message(user_id, command, chat_id, message.bot)
    cmd = "ps aux --sort=-%cpu | head -n 11"
    process = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    if process.returncode == 0:
        raw_output = stdout.decode("utf-8", errors="ignore").strip()
        lines = raw_output.split('\n')
        formatted_lines = []
        
        # Skip header line, process up to 10 lines
        for line in lines[1:]:
            parts = line.split(None, 10)
            if len(parts) >= 11:
                user, pid, cpu, mem, vsz, rss, tty, stat, start, time, command = parts
                
                # Format memory (VSZ and RSS are in KB)
                try:
                    vsz_mb = f"{int(vsz) / 1024:.1f}M"
                    rss_mb = f"{int(rss) / 1024:.1f}M"
                except ValueError:
                    vsz_mb = vsz
                    rss_mb = rss

                # Keep command name short and clean
                short_cmd = command.split()[0].split('/')[-1]
                if len(short_cmd) > 15:
                    short_cmd = short_cmd[:12] + "..."
                    
                line1 = f"🖥 <b>{escape_html(short_cmd)}</b> (<code>{pid}</code>)"
                line2 = f"👤 <b>{user}</b> | ⏳ <b>{time}</b> | 🔄 <b>{stat}</b>"
                line3 = f"🔥 CPU: <b>{cpu}%</b> | 💾 RAM: <b>{mem}%</b> ({vsz_mb} / {rss_mb})"
                formatted_lines.append(f"{line1}\n{line2}\n{line3}")
                
        if not formatted_lines:
            output_str = "No processes found."
            response_text = _("top_header", lang, output=output_str)
            await message.answer(response_text, parse_mode="HTML")
            return

        # Attempt to use the new RichMessage API
        import aiohttp
        try:
            api_url = f"https://api.telegram.org/bot{message.bot.token}/sendRichMessage"
            
            # Construct table rows
            table_rows = []
            
            # Helper to create a cell
            def make_cell(text, is_bold=False):
                # We will just try a basic paragraph block inside
                # Telegram's RichMessage blocks are extremely nested
                content = {
                    "type": "paragraph",
                    "text": {"text": str(text)}
                }
                if is_bold:
                    # add entities if we want, but let's keep it simple
                    pass
                return {"type": "tableCell", "content": content}

            # Header row
            table_rows.append({
                "type": "tableRow",
                "cells": [
                    make_cell("CMD", True),
                    make_cell("PID", True),
                    make_cell("USER", True),
                    make_cell("CPU%", True),
                    make_cell("RAM%", True)
                ]
            })

            # Data rows
            # We already parsed the lines above, so let's re-use the parsed data
            # formatted_lines has strings, let's extract data from the raw lines again
            for line in lines[1:11]: # max 10 processes
                parts = line.split(None, 10)
                if len(parts) >= 11:
                    p_user, p_pid, p_cpu, p_mem, p_vsz, p_rss, p_tty, p_stat, p_start, p_time, p_command = parts
                    short_cmd = p_command.split()[0].split('/')[-1][:12]
                    
                    table_rows.append({
                        "type": "tableRow",
                        "cells": [
                            make_cell(short_cmd),
                            make_cell(p_pid),
                            make_cell(p_user),
                            make_cell(p_cpu),
                            make_cell(p_mem)
                        ]
                    })

            payload = {
                "chat_id": chat_id,
                "rich_message": {
                    "blocks": [
                        {
                            "type": "sectionHeading",
                            "text": {"text": "🔥 Top processes by CPU load"}
                        },
                        {
                            "type": "table",
                            "rows": table_rows
                        }
                    ]
                }
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(api_url, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        sent_message_id = data.get("result", {}).get("message_id")
                        if sent_message_id:
                            LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message_id
                        return
                    else:
                        # Fallback if the experimental JSON structure is rejected
                        pass
        except Exception as e:
            # Fallback on any error
            pass

        # Fallback to card design if sendRichMessage fails
        output_str = "\n\n".join(formatted_lines)
        response_text = _("top_header", lang, output=output_str)
    else:
        error_output = escape_html(stderr.decode())
        response_text = _("top_fail", lang, error=error_output)
    sent_message = await message.answer(response_text, parse_mode="HTML")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
