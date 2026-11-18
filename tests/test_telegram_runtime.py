import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]


class NetworkError(Exception):
    pass


class RetryAfter(Exception):
    def __init__(self, seconds):
        self.retry_after = seconds


def load_runtime():
    # Other legacy tests replace aiogram globally. Keep these tests isolated.
    spec = importlib.util.spec_from_file_location("telegram_runtime_subject", ROOT / "core/telegram_runtime.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {
        "aiogram": SimpleNamespace(Bot=object, Dispatcher=object),
        "aiogram.exceptions": SimpleNamespace(
            TelegramNetworkError=NetworkError, TelegramRetryAfter=RetryAfter, TelegramServerError=NetworkError,
        ),
    }):
        spec.loader.exec_module(module)
    return module


class TelegramStartupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.subject = load_runtime()
        self.bot = SimpleNamespace(delete_webhook=AsyncMock(return_value=True), me=AsyncMock())

    async def test_retries_each_startup_operation_independently(self):
        self.bot.delete_webhook.side_effect = [NetworkError(), True]
        self.bot.me.side_effect = [asyncio.TimeoutError(), object()]
        with patch.object(self.subject.asyncio, "sleep", new_callable=AsyncMock) as sleep:
            await self.subject.prepare_bot(self.bot)
        self.assertEqual(self.bot.delete_webhook.await_count, 2)
        self.assertEqual(self.bot.me.await_count, 2)
        self.assertEqual([call.args[0] for call in sleep.await_args_list], [2, 2])

    async def test_exhaustion_does_not_sleep_or_start_polling(self):
        self.bot.delete_webhook.side_effect = NetworkError("offline")
        dispatcher = SimpleNamespace(start_polling=AsyncMock())
        with patch.object(self.subject.asyncio, "sleep", new_callable=AsyncMock) as sleep:
            with self.assertRaises(NetworkError):
                await self.subject.run_polling(self.bot, dispatcher, allowed_updates=[])
        self.assertEqual(self.bot.delete_webhook.await_count, 5)
        self.assertEqual(sleep.await_count, 4)
        self.bot.me.assert_not_awaited()
        dispatcher.start_polling.assert_not_awaited()

    async def test_retry_after_is_respected_except_after_last_attempt(self):
        self.bot.delete_webhook.side_effect = RetryAfter(17)
        with patch.object(self.subject.asyncio, "sleep", new_callable=AsyncMock) as sleep:
            with self.assertRaises(RetryAfter):
                await self.subject.prepare_bot(self.bot, max_attempts=2)
        sleep.assert_awaited_once_with(17)

    async def test_permanent_errors_and_false_response_do_not_retry(self):
        self.bot.delete_webhook.side_effect = ValueError("invalid configuration")
        with self.assertRaises(ValueError):
            await self.subject.prepare_bot(self.bot)
        self.bot.delete_webhook.assert_awaited_once()
        self.bot.delete_webhook.side_effect = None
        self.bot.delete_webhook.return_value = False
        with self.assertRaisesRegex(RuntimeError, "did not confirm"):
            await self.subject.prepare_bot(self.bot)
        self.bot.me.assert_not_awaited()

    async def test_request_timeout_cancels_inflight_request(self):
        cancelled = asyncio.Event()

        async def blocked(**kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        self.bot.delete_webhook.side_effect = blocked
        with self.assertRaises(asyncio.TimeoutError):
            await self.subject.prepare_bot(self.bot, max_attempts=1, request_timeout=0.01)
        self.assertTrue(cancelled.is_set())

    async def test_cancellation_interrupts_backoff_without_starting_dispatcher(self):
        self.bot.delete_webhook.side_effect = RetryAfter(3600)
        sleeping = asyncio.Event()

        async def sleep(_delay):
            sleeping.set()
            await asyncio.Event().wait()

        dispatcher = SimpleNamespace(start_polling=AsyncMock())
        with patch.object(self.subject.asyncio, "sleep", side_effect=sleep):
            task = asyncio.create_task(self.subject.run_polling(self.bot, dispatcher, allowed_updates=[]))
            await sleeping.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.bot.delete_webhook.assert_awaited_once()
        dispatcher.start_polling.assert_not_awaited()

    async def test_cancellation_drains_dispatcher_and_preserves_session_ownership(self):
        started, stopped, finalized = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def poll(*args, **kwargs):
            started.set()
            try:
                await stopped.wait()
            finally:
                finalized.set()

        async def stop():
            stopped.set()
            await finalized.wait()

        dispatcher = SimpleNamespace(
            start_polling=AsyncMock(side_effect=poll), stop_polling=AsyncMock(side_effect=stop),
        )
        task = asyncio.create_task(self.subject.run_polling(self.bot, dispatcher, allowed_updates=["message"]))
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(finalized.is_set())
        dispatcher.start_polling.assert_awaited_once_with(
            self.bot, allowed_updates=["message"], handle_signals=False, close_bot_session=False,
        )
        dispatcher.stop_polling.assert_awaited_once()

    async def test_dispatcher_error_propagates_without_restart(self):
        dispatcher = SimpleNamespace(start_polling=AsyncMock(side_effect=NetworkError("startup callback")))
        with self.assertRaises(NetworkError):
            await self.subject.run_polling(self.bot, dispatcher, allowed_updates=[])
        dispatcher.start_polling.assert_awaited_once()

    def test_signal_cancels_startup_once_even_before_polling(self):
        # Exercise the production function directly without evaluating AST or importing bot.py.
        loop, main_task = Mock(), Mock()
        self.subject._install_shutdown_signal_handlers(loop, main_task)
        for call in loop.add_signal_handler.call_args_list:
            sig, callback, arg = call.args
            self.assertIn(sig, (self.subject.signal.SIGINT, self.subject.signal.SIGTERM))
            callback(arg)
        main_task.cancel.assert_called_once()


if __name__ == "__main__":
    unittest.main()
