"""Dependency stubs for tests that do not need the Telegram runtime."""
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock


CORE_DEPENDENCIES = (
    "aiohttp", "aiohttp.web", "argon2", "argon2.exceptions", "aiosqlite",
    "requests", "PIL", "PIL.Image", "qrcode", "netifaces", "sentry_sdk",
    "yaml", "docker", "asyncssh", "tortoise",
)
AIOGRAM_DEPENDENCIES = (
    "aiogram", "aiogram.filters", "aiogram.fsm", "aiogram.fsm.context",
    "aiogram.fsm.state", "aiogram.fsm.storage", "aiogram.fsm.storage.memory",
    "aiogram.types", "aiogram.exceptions",
)


def mock_optional_modules(names):
    for name in names:
        if name not in sys.modules:
            module = MagicMock()
            module.__path__ = []
            module.__spec__ = SimpleNamespace(name=name, origin=None, submodule_search_locations=[])
            sys.modules[name] = module
