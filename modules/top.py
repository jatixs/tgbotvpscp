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
        if not lines[1:]:
            output_str = "No processes found."
            response_text = _("top_header", lang, output=output_str)
            await message.answer(response_text, parse_mode="HTML")
            return

        # Format as a clean, mobile-friendly ASCII table inside <pre>
        # We limit columns to fit within ~40-45 chars for mobile
        table_lines = []
        table_lines.append(f"{'PID':<7} {'USER':<8} {'CPU':<4} {'RAM':<4} {'TIME':<5} {'CMD'}")
        table_lines.append("-" * 42)
        
        for line in lines[1:11]: # max 10 processes
            parts = line.split(None, 10)
            if len(parts) >= 11:
                p_user, p_pid, p_cpu, p_mem, p_vsz, p_rss, p_tty, p_stat, p_start, p_time, p_command = parts
                
                # Truncate user
                if len(p_user) > 7:
                    p_user = p_user[:6] + "+"
                    
                # Truncate command
                short_cmd = p_command.split()[0].split('/')[-1]
                if len(short_cmd) > 10:
                    short_cmd = short_cmd[:9] + "…"
                    
                # Format numbers
                try:
                    cpu_val = float(p_cpu)
                    cpu_str = f"{cpu_val:.1f}" if cpu_val < 100 else f"{int(cpu_val)}"
                except ValueError:
                    cpu_str = p_cpu[:4]
                    
                try:
                    mem_val = float(p_mem)
                    mem_str = f"{mem_val:.1f}" if mem_val < 100 else f"{int(mem_val)}"
                except ValueError:
                    mem_str = p_mem[:4]
                    
                time_str = p_time[:5]
                
                table_lines.append(f"{p_pid:<7} {p_user:<8} {cpu_str:>4} {mem_str:>4} {time_str:>5} {escape_html(short_cmd)}")

        output_str = "<pre>" + "\n".join(table_lines) + "</pre>"
        response_text = _("top_header", lang, output=output_str)
    else:
        error_output = escape_html(stderr.decode())
        response_text = _("top_fail", lang, error=error_output)
    sent_message = await message.answer(response_text, parse_mode="HTML")
    LAST_MESSAGE_IDS.setdefault(user_id, {})[command] = sent_message.message_id
