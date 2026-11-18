"""Exercise real aiogram in a subprocess, isolated from legacy sys.modules mocks."""

import asyncio
import multiprocessing
import unittest


def _run_telegram_scenario():
    # Keep aiogram and its module imports isolated from legacy global mocks.
    asyncio.run(scenario())


class AiogramLifecycleTests(unittest.TestCase):
    def test_real_dispatcher_retries_identity_and_drains_on_cancellation(self):
        process = multiprocessing.get_context("spawn").Process(target=_run_telegram_scenario)
        process.start()
        process.join(timeout=20)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
            self.fail("Telegram integration scenario timed out")
        self.assertEqual(process.exitcode, 0, f"Telegram scenario exited with {process.exitcode}")

async def scenario():
    from collections import Counter
    from unittest.mock import patch

    from aiogram import Bot, Dispatcher
    from aiogram.client.session.base import BaseSession
    from aiogram.exceptions import TelegramNetworkError, TelegramServerError
    from aiogram.methods import DeleteWebhook, GetMe, GetUpdates
    from aiogram.types import User

    from core import telegram_runtime

    class Session(BaseSession):
        def __init__(self):
            super().__init__()
            self.calls = Counter()
            self.started = asyncio.Event()
            self.closed = 0

        async def close(self):
            self.closed += 1

        async def make_request(self, bot, method, timeout=None):
            self.calls[type(method)] += 1
            if isinstance(method, DeleteWebhook):
                if self.calls[DeleteWebhook] == 1:
                    raise TelegramNetworkError(method=method, message="offline")
                return True
            if isinstance(method, GetMe):
                if self.calls[GetMe] == 1:
                    raise TelegramServerError(method=method, message="temporary outage")
                return User(id=123456, is_bot=True, first_name="Test", username="test_bot")
            if isinstance(method, GetUpdates):
                self.started.set()
                await asyncio.Event().wait()
            raise AssertionError(type(method))

        async def stream_content(self, *args, **kwargs):
            yield b""

    # Check normal shutdown and a failing shutdown callback: neither may leak
    # a polling task or leave stop_polling waiting forever.
    for fail_shutdown in (False, True):
        session = Session()
        bot = Bot("123456:TEST_TOKEN", session=session)
        dispatcher = Dispatcher()
        lifecycle = []

        async def startup():
            lifecycle.append("startup")

        async def shutdown():
            lifecycle.append("shutdown")
            if fail_shutdown:
                raise RuntimeError("shutdown callback failed")

        dispatcher.startup.register(startup)
        dispatcher.shutdown.register(shutdown)
        prepare = telegram_runtime.prepare_bot
        with patch.object(telegram_runtime, "prepare_bot", lambda bot: prepare(bot, initial_delay=0)):
            task = asyncio.create_task(telegram_runtime.run_polling(bot, dispatcher, allowed_updates=["message"]))
            await asyncio.wait_for(session.started.wait(), timeout=5)
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=5)
            except asyncio.CancelledError:
                pass
            else:
                raise AssertionError("Cancellation was swallowed")
        assert lifecycle == ["startup", "shutdown"], lifecycle
        assert session.calls[DeleteWebhook] == 2, session.calls
        assert session.calls[GetMe] == 2, session.calls  # Dispatcher uses the warmed cache.
        assert session.closed == 0  # The caller closes the session after other services.
        await bot.session.close()
        assert session.closed == 1
        assert not [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]


if __name__ == "__main__":
    unittest.main()
