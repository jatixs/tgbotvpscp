"""Prepare Telegram polling with bounded retries and an explicit task lifetime."""

import asyncio
import logging
import signal
import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter, TelegramServerError
from aiogram.utils.backoff import BackoffConfig


POLLING_TIMEOUT = 20
POLLING_BACKOFF = BackoffConfig(min_delay=2.0, max_delay=30.0, factor=1.6, jitter=0.5)
_polling_log_context: ContextVar[Any] = ContextVar("telegram_polling_log_context", default=None)


class PollingLogFilter(logging.Filter):
    """Summarize transient polling outages without hiding permanent API errors."""

    def __init__(self, bot_id: int):
        super().__init__()
        self.bot_id = bot_id
        self.started = None
        self.last_report = None
        self.failures = 0
        self.transient = False

    def filter(self, record: logging.LogRecord) -> bool:
        if _polling_log_context.get() is not self:
            return True
        if record.msg == "Failed to fetch updates - %s: %s":
            self.transient = bool(record.args and record.args[0] in {
                "TelegramNetworkError", "TelegramServerError",
            })
            if not self.transient:
                return True
            now = time.monotonic()
            first = self.started is None
            if first:
                self.started = now
            self.failures += 1
            duration = now - self.started
            report = first or now - self.last_report >= 60
            level = logging.INFO if first else logging.DEBUG
            if report and not first:
                level = logging.ERROR if duration >= 300 else logging.WARNING
            if report:
                self.last_report = now
            error_type, error = record.args
            record.msg = "Telegram polling reconnecting (bot id=%s, failures=%d, outage=%.0fs): %s: %s"
            record.args = (self.bot_id, self.failures, duration, error_type, error)
        elif record.msg == "Sleep for %f seconds and try again... (tryings = %d, bot id = %d)" and self.transient:
            level = logging.DEBUG
        elif record.msg == "Connection established (tryings = %d, bot id = %d)" and self.started is not None:
            record.msg = "Telegram polling restored (bot id=%s, retries=%d, outage=%.1fs)"
            record.args = (self.bot_id, self.failures, time.monotonic() - self.started)
            self.started = self.last_report = None
            self.failures = 0
            self.transient = False
            level = logging.INFO
        else:
            return True
        record.levelno = level
        record.levelname = logging.getLevelName(level)
        return logging.getLogger(record.name).isEnabledFor(level)


async def _retry_startup(
    operation: Callable[[], Awaitable[Any]],
    name: str,
    *,
    max_attempts: int,
    request_timeout: float,
    initial_delay: float,
) -> Any:
    for attempt in range(1, max_attempts + 1):
        try:
            return await asyncio.wait_for(operation(), timeout=request_timeout)
        except (TelegramNetworkError, asyncio.TimeoutError, TelegramRetryAfter, TelegramServerError) as exc:
            err_msg = str(exc).strip() or type(exc).__name__
            if attempt == max_attempts:
                logging.error("Telegram %s failed after %d attempts: %s", name, max_attempts, err_msg)
                raise
            delay = (max(float(exc.retry_after), initial_delay)
                     if isinstance(exc, TelegramRetryAfter) else initial_delay * attempt)
            logging.warning("Telegram %s attempt %d/%d failed: %s. Retrying in %.1fs",
                            name, attempt, max_attempts, err_msg, delay)
            await asyncio.sleep(delay)


async def prepare_bot(
    bot: Bot,
    *,
    max_attempts: int = 5,
    request_timeout: float = 30,
    initial_delay: float = 2,
) -> None:
    """Clear the webhook and warm aiogram's cached identity before polling.

    Cancellation interrupts requests and backoff. If Telegram is slow or has
    a large pending queue, drop_pending_updates=True can time out; retries
    fall back to lightweight deletion without dropping updates so polling
    is not blocked.
    """
    if max_attempts < 1 or request_timeout <= 0 or initial_delay < 0:
        raise ValueError("Invalid Telegram startup retry settings")

    # Clear webhook: try drop_pending_updates=True on first attempt;
    # on retry, switch to drop_pending_updates=False to avoid timing out on large queues.
    for attempt in range(1, max_attempts + 1):
        drop_updates = (attempt == 1)
        try:
            cleared = await asyncio.wait_for(
                bot.delete_webhook(drop_pending_updates=drop_updates, request_timeout=request_timeout),
                timeout=request_timeout,
            )
            if cleared is False:
                raise RuntimeError("Telegram did not confirm webhook deletion")
            break
        except (TelegramNetworkError, asyncio.TimeoutError, TelegramRetryAfter, TelegramServerError) as exc:
            err_msg = str(exc).strip() or type(exc).__name__
            if attempt == max_attempts:
                logging.error("Telegram deleteWebhook failed after %d attempts: %s", max_attempts, err_msg)
                raise
            delay = (max(float(exc.retry_after), initial_delay)
                     if isinstance(exc, TelegramRetryAfter) else initial_delay * attempt)
            logging.warning("Telegram deleteWebhook attempt %d/%d failed: %s. Retrying in %.1fs",
                            attempt, max_attempts, err_msg, delay)
            await asyncio.sleep(delay)

    policy = dict(max_attempts=max_attempts, request_timeout=request_timeout, initial_delay=initial_delay)
    await _retry_startup(bot.me, "getMe", **policy)


async def run_polling(bot: Bot, dispatcher: Dispatcher, *, allowed_updates: list[str]) -> None:
    """Start the dispatcher once; let aiogram retry getUpdates internally.

    The caller owns the bot session. Shield polling from task cancellation so
    stop_polling can stop its internal tasks and run shutdown callbacks first.
    """
    await prepare_bot(bot)
    logger = logging.getLogger("aiogram.dispatcher")
    log_filter = PollingLogFilter(bot.id)
    logger.addFilter(log_filter)
    token = _polling_log_context.set(log_filter)
    try:
        polling = asyncio.create_task(dispatcher.start_polling(
            bot, allowed_updates=allowed_updates, handle_signals=False, close_bot_session=False,
            polling_timeout=POLLING_TIMEOUT, backoff_config=POLLING_BACKOFF,
        ))
    except Exception:
        logger.removeFilter(log_filter)
        raise
    finally:
        _polling_log_context.reset(token)
    try:
        await asyncio.shield(polling)
    except asyncio.CancelledError:
        if not polling.done():
            stop = asyncio.create_task(dispatcher.stop_polling())
            try:
                # A startup/shutdown callback may fail without aiogram setting its
                # stopped event. In that case the polling task is authoritative.
                await asyncio.wait((polling, stop), return_when=asyncio.FIRST_COMPLETED)
                if stop.done():
                    try:
                        stop.result()
                    except RuntimeError:
                        # Cancellation won the race before the dispatcher started.
                        polling.cancel()
                await asyncio.gather(polling, return_exceptions=True)
            finally:
                stop.cancel()
                await asyncio.gather(stop, return_exceptions=True)
        await asyncio.gather(polling, return_exceptions=True)
        raise
    finally:
        logger.removeFilter(log_filter)


def _install_shutdown_signal_handlers(loop: asyncio.AbstractEventLoop, main_task: asyncio.Task) -> None:
    # Own the single process-wide SIGINT/SIGTERM handler instead of letting aiogram's
    # start_polling(handle_signals=True) register one per dispatcher: with two dispatchers
    # (main bot + Alert Bot) polling concurrently, the second registration silently
    # overwrites the first, so the main bot never learns about the stop signal and hangs
    # until systemd's stop-sigterm timeout kills the process and its subprocesses.
    stopping = False

    def _on_signal(sig: signal.Signals) -> None:
        nonlocal stopping
        if stopping:
            return
        stopping = True
        logging.warning(f"Received {sig.name} signal. Initiating graceful shutdown...")
        # Also interrupts startup requests/backoff before a dispatcher is running.
        # run_polling drains the dispatcher before main's finally closes resources.
        main_task.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _on_signal, sig)
        except NotImplementedError:
            pass  # Not supported on Windows event loops; rely on KeyboardInterrupt instead.

