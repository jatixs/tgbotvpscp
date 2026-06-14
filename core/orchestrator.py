"""
Memory Orchestrator — Lazy Module Loader for VPS Manager Bot.

Manages the lifecycle of bot modules to minimize RAM usage on low-resource VPS.
Modules are divided into tiers:
  - ALWAYS_ON  (Tier 0): Loaded at startup, never unloaded (e.g., notifications).
  - ON_DEMAND  (Tier 1): Loaded when a user triggers them, unloaded after TTL.

The orchestrator registers lightweight proxy handlers at startup. When a user
triggers a command, the proxy loads the real module via importlib and delegates.
After a period of inactivity (TTL), the module is unloaded from sys.modules and
gc.collect() is called to free memory.
"""

import asyncio
import gc
import importlib
import inspect
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import psutil


def _filter_kwargs(func, kwargs: dict) -> dict:
    """Filters kwargs to only pass arguments that the target function actually accepts."""
    sig = inspect.signature(func)
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
        return kwargs
    valid_keys = {
        p.name for p in sig.parameters.values()
        if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }
    return {k: v for k, v in kwargs.items() if k in valid_keys}


class ModuleTier(Enum):
    """Module loading tier."""
    ALWAYS_ON = 0
    ON_DEMAND = 1


class ModuleState(Enum):
    """Module lifecycle state."""
    UNLOADED = "unloaded"
    LOADING = "loading"
    LOADED = "loaded"


@dataclass
class ModuleInfo:
    """Metadata for a registered module."""
    name: str
    tier: ModuleTier
    state: ModuleState = ModuleState.UNLOADED
    last_used: float = 0.0
    load_count: int = 0
    last_load_time_ms: float = 0.0
    rss_delta_bytes: int = 0
    has_background_tasks: bool = False
    background_tasks: list = field(default_factory=list)
    # Snapshot of sys.modules keys BEFORE loading this module
    _pre_load_modules: set = field(default_factory=set, repr=False)


class HandlerCollector:
    """
    Mimics the Aiogram Dispatcher API to capture handler registrations.

    When a module calls register_handlers(collector), the collector records
    each handler's filters and function name without actually registering
    them on the real Dispatcher.
    """

    def __init__(self):
        self.message_handlers: list[tuple[tuple, str]] = []
        self.callback_handlers: list[tuple[tuple, str]] = []
        self._routers: list = []

    def message(self, *filters):
        """Capture message handler registration."""
        def decorator(func):
            self.message_handlers.append((filters, func.__name__))
            return func
        return decorator

    def callback_query(self, *filters):
        """Capture callback_query handler registration."""
        obj = _CallbackQueryCollector(self)
        return obj(*filters)

    def include_router(self, router):
        """Capture router inclusion — extract handlers from the router."""
        self._routers.append(router)

    class _InnerCallbackQuery:
        """Handles the .register() API variant used by some modules."""
        def __init__(self, parent):
            self._parent = parent

        def register(self, handler, *filters):
            self._parent.callback_handlers.append((filters, handler.__name__))

    @property
    def callback_query_obj(self):
        return self._InnerCallbackQuery(self)


class _CallbackQueryCollector:
    """
    Helper that handles both decorator-style and .register() style
    callback_query registrations.
    """

    def __init__(self, collector: HandlerCollector):
        self._collector = collector

    def __call__(self, *filters):
        """decorator-style: dp.callback_query(F.data == "x")(handler)"""
        def decorator(func):
            self._collector.callback_handlers.append((filters, func.__name__))
            return func
        return decorator

    def register(self, handler, *filters):
        """register-style: dp.callback_query.register(handler, filter)"""
        self._collector.callback_handlers.append((filters, handler.__name__))


class _DispatcherProxy:
    """
    Wraps a HandlerCollector to present the same API as aiogram.Dispatcher.

    Modules call dp.message(...), dp.callback_query(...), dp.callback_query.register(...),
    and dp.include_router(...). This proxy captures all of them.
    """

    def __init__(self, collector: HandlerCollector):
        self._collector = collector
        self.callback_query = _CallbackQueryCollector(collector)

    def message(self, *filters):
        return self._collector.message(*filters)

    def include_router(self, router):
        self._collector.include_router(router)


class ModuleOrchestrator:
    """
    Central orchestrator for lazy module loading/unloading.

    Usage:
        orchestrator = ModuleOrchestrator(dp, bot, module_config, unload_ttl=300)
        await orchestrator.setup()
        await orchestrator.start_gc()
        ...
        await orchestrator.shutdown()
    """

    def __init__(self, dp, bot, module_config: dict[str, dict], unload_ttl: int = 300):
        """
        Args:
            dp: The real aiogram Dispatcher.
            bot: The aiogram Bot instance.
            module_config: Dict mapping module name to config dict with keys:
                - "tier": ModuleTier
                - "admin_only": bool (optional)
                - "root_only": bool (optional)
            unload_ttl: Seconds of inactivity before unloading ON_DEMAND modules.
        """
        self._dp = dp
        self._bot = bot
        self._config = module_config
        self._unload_ttl = unload_ttl
        self._modules: dict[str, ModuleInfo] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._gc_task: Optional[asyncio.Task] = None
        self._background_tasks: set[asyncio.Task] = set()
        self._setup_done = False

    @property
    def background_tasks(self) -> set[asyncio.Task]:
        """All background tasks started by modules."""
        return self._background_tasks

    async def setup(self):
        """
        Initialize the orchestrator:
          1. For ALWAYS_ON modules: import, register handlers, start tasks.
          2. For ON_DEMAND modules: collect handlers via proxy, register proxies.
        """
        logging.info("🧠 Memory Orchestrator: Setting up...")

        for module_name, mod_config in self._config.items():
            tier = mod_config["tier"]
            info = ModuleInfo(name=module_name, tier=tier)
            self._modules[module_name] = info
            self._locks[module_name] = asyncio.Lock()

            if tier == ModuleTier.ALWAYS_ON:
                await self._load_always_on(module_name, info)
            else:
                self._register_lazy_handlers(module_name, info)

        self._setup_done = True
        loaded = sum(1 for m in self._modules.values() if m.state == ModuleState.LOADED)
        total = len(self._modules)
        logging.info(f"🧠 Memory Orchestrator: Setup complete. {loaded}/{total} modules loaded.")

    async def _load_always_on(self, module_name: str, info: ModuleInfo):
        """Load an ALWAYS_ON module immediately."""
        try:
            module = importlib.import_module(module_name)
            info.state = ModuleState.LOADED
            info.last_used = time.time()
            info.load_count = 1

            if hasattr(module, "register_handlers"):
                module.register_handlers(self._dp)

            if hasattr(module, "start_background_tasks"):
                info.has_background_tasks = True
                tasks = module.start_background_tasks(self._bot)
                if tasks:
                    for task in tasks:
                        self._background_tasks.add(task)
                        info.background_tasks.append(task)

            logging.info(f"  ✅ {module_name} (always-on) loaded.")
        except Exception as e:
            logging.error(f"  ❌ Failed to load {module_name}: {e}", exc_info=True)

    def _register_lazy_handlers(self, module_name: str, info: ModuleInfo):
        """
        Temporarily import the module to collect its handler registrations,
        then unload it and register proxy handlers on the real dispatcher.
        """
        try:
            # Snapshot sys.modules before import
            pre_modules = set(sys.modules.keys())

            # Import module to collect handlers
            module = importlib.import_module(module_name)

            # Collect handlers via proxy dispatcher
            collector = HandlerCollector()
            proxy_dp = _DispatcherProxy(collector)

            if hasattr(module, "register_handlers"):
                module.register_handlers(proxy_dp)

            # Check if module has background tasks
            info.has_background_tasks = hasattr(module, "start_background_tasks")

            # Save the set of new modules introduced by this import
            info._pre_load_modules = pre_modules

            # Unload the module and its unique dependencies
            self._unload_module_from_sys(module_name, pre_modules)
            del module
            gc.collect()

            # Register proxy handlers on the real dispatcher
            self._register_proxies_from_collector(module_name, collector)

            logging.info(
                f"  ⏸️  {module_name} (on-demand) — "
                f"{len(collector.message_handlers)} msg + "
                f"{len(collector.callback_handlers)} cb handlers registered as proxies."
            )
        except Exception as e:
            logging.error(f"  ❌ Failed to setup lazy handlers for {module_name}: {e}", exc_info=True)
            # Fallback: load normally
            try:
                module = importlib.import_module(module_name)
                info.state = ModuleState.LOADED
                if hasattr(module, "register_handlers"):
                    module.register_handlers(self._dp)
                logging.warning(f"  ⚠️  {module_name} loaded as fallback (no lazy loading).")
            except Exception as e2:
                logging.error(f"  ❌ Fallback load also failed for {module_name}: {e2}")

    def _register_proxies_from_collector(self, module_name: str, collector: HandlerCollector):
        """Register proxy handlers on the real dispatcher from collected handler info."""

        # Register message handler proxies
        for filters, func_name in collector.message_handlers:
            proxy = self._create_proxy_handler(module_name, func_name, is_callback=False)
            self._dp.message(*filters)(proxy)

        # Register callback handler proxies
        for filters, func_name in collector.callback_handlers:
            proxy = self._create_proxy_handler(module_name, func_name, is_callback=True)
            # Use the decorator-style registration
            self._dp.callback_query(*filters)(proxy)

        # Handle routers (e.g., logs.py uses dp.include_router(router))
        for router in collector._routers:
            self._dp.include_router(router)

    def _create_proxy_handler(self, module_name: str, func_name: str, is_callback: bool):
        """
        Create a lightweight proxy handler that loads the module on first call
        and delegates to the real handler.
        """
        orchestrator = self  # capture reference

        if is_callback:
            async def proxy_callback_handler(callback, *args, **kwargs):
                module = await orchestrator.ensure_loaded(module_name)
                real_handler = getattr(module, func_name)
                filtered_kwargs = _filter_kwargs(real_handler, kwargs)
                return await real_handler(callback, *args, **filtered_kwargs)
            proxy_callback_handler.__name__ = f"proxy_{module_name}_{func_name}"
            proxy_callback_handler.__qualname__ = f"proxy_{module_name}_{func_name}"
            return proxy_callback_handler
        else:
            async def proxy_message_handler(message, *args, **kwargs):
                module = await orchestrator.ensure_loaded(module_name)
                real_handler = getattr(module, func_name)
                filtered_kwargs = _filter_kwargs(real_handler, kwargs)
                return await real_handler(message, *args, **filtered_kwargs)
            proxy_message_handler.__name__ = f"proxy_{module_name}_{func_name}"
            proxy_message_handler.__qualname__ = f"proxy_{module_name}_{func_name}"
            return proxy_message_handler

    async def ensure_loaded(self, module_name: str):
        """
        Ensure a module is loaded and return the module object.
        Thread-safe via per-module asyncio.Lock.
        """
        info = self._modules.get(module_name)
        if not info:
            raise ValueError(f"Unknown module: {module_name}")

        # Fast path: already loaded
        if info.state == ModuleState.LOADED and module_name in sys.modules:
            info.last_used = time.time()
            return sys.modules[module_name]

        async with self._locks[module_name]:
            # Double-check after acquiring lock
            if info.state == ModuleState.LOADED and module_name in sys.modules:
                info.last_used = time.time()
                return sys.modules[module_name]

            info.state = ModuleState.LOADING
            start_time = time.time()
            rss_before = self._get_process_rss()

            try:
                module = importlib.import_module(module_name)
                info.state = ModuleState.LOADED
                info.last_used = time.time()
                info.load_count += 1
                info.last_load_time_ms = (time.time() - start_time) * 1000
                info.rss_delta_bytes = self._get_process_rss() - rss_before

                # Start background tasks if the module has them
                if info.has_background_tasks and hasattr(module, "start_background_tasks"):
                    tasks = module.start_background_tasks(self._bot)
                    if tasks:
                        for task in tasks:
                            self._background_tasks.add(task)
                            info.background_tasks.append(task)

                logging.info(
                    f"🧠 Loaded {module_name} in {info.last_load_time_ms:.0f}ms "
                    f"(+{info.rss_delta_bytes // 1024}KB RSS)"
                )
                return module

            except Exception as e:
                info.state = ModuleState.UNLOADED
                logging.error(f"🧠 Failed to load {module_name}: {e}", exc_info=True)
                raise

    async def unload_module(self, module_name: str):
        """Unload an ON_DEMAND module from memory."""
        info = self._modules.get(module_name)
        if not info or info.tier == ModuleTier.ALWAYS_ON:
            return

        async with self._locks[module_name]:
            if info.state != ModuleState.LOADED:
                return

            # Cancel background tasks
            for task in info.background_tasks:
                if task and not task.done():
                    task.cancel()
                    try:
                        await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        pass
                self._background_tasks.discard(task)
            info.background_tasks.clear()

            # Unload from sys.modules
            rss_before = self._get_process_rss()
            self._unload_module_from_sys(module_name, info._pre_load_modules)
            gc.collect()
            rss_after = self._get_process_rss()
            freed = rss_before - rss_after

            info.state = ModuleState.UNLOADED
            logging.info(f"🧠 Unloaded {module_name} (freed ~{max(0, freed) // 1024}KB)")

    def _unload_module_from_sys(self, module_name: str, pre_modules: set):
        """
        Remove the module and its exclusive dependencies from sys.modules.

        Only removes modules that were NOT in sys.modules before the target
        module was imported, to avoid breaking shared dependencies.
        """
        # Remove the module itself
        sys.modules.pop(module_name, None)

        # Remove submodules of the module (e.g., modules.services.xyz)
        prefix = module_name + "."
        to_remove = [key for key in sys.modules if key.startswith(prefix)]
        for key in to_remove:
            sys.modules.pop(key, None)

        # We intentionally do NOT remove shared dependencies (e.g., psutil, aiohttp)
        # because they are likely used by other parts of the system. Removing only
        # the module itself is safe and sufficient to free its code objects and caches.

    async def start_gc(self):
        """Start the background garbage collection loop."""
        self._gc_task = asyncio.create_task(self._gc_loop(), name="OrchestratorGC")
        self._background_tasks.add(self._gc_task)
        logging.info("🧠 Memory Orchestrator GC loop started.")

    async def _gc_loop(self):
        """Periodically check and unload inactive ON_DEMAND modules."""
        while True:
            try:
                await asyncio.sleep(60)  # Check every 60 seconds
                now = time.time()
                for module_name, info in self._modules.items():
                    if (
                        info.tier == ModuleTier.ON_DEMAND
                        and info.state == ModuleState.LOADED
                        and (now - info.last_used) > self._unload_ttl
                    ):
                        await self.unload_module(module_name)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logging.error(f"🧠 GC loop error: {e}", exc_info=True)

    async def shutdown(self):
        """Gracefully stop the orchestrator."""
        if self._gc_task and not self._gc_task.done():
            self._gc_task.cancel()
        logging.info("🧠 Memory Orchestrator shut down.")

    def get_stats(self) -> dict:
        """Get current memory orchestrator statistics."""
        process = psutil.Process(os.getpid())
        rss = process.memory_info().rss

        modules_stats = []
        for name, info in self._modules.items():
            modules_stats.append({
                "name": name,
                "tier": info.tier.name.lower(),
                "state": info.state.value,
                "last_used": info.last_used,
                "load_count": info.load_count,
                "last_load_time_ms": info.last_load_time_ms,
                "rss_delta_bytes": info.rss_delta_bytes,
                "has_bg_tasks": info.has_background_tasks,
            })

        loaded = sum(1 for m in self._modules.values() if m.state == ModuleState.LOADED)
        total = len(self._modules)

        return {
            "total_rss_bytes": rss,
            "loaded_count": loaded,
            "total_count": total,
            "unload_ttl_sec": self._unload_ttl,
            "modules": modules_stats,
        }

    def format_stats(self, lang: str = "ru") -> str:
        """Format stats as a human-readable Telegram message."""
        stats = self.get_stats()
        rss_mb = stats["total_rss_bytes"] / (1024 * 1024)

        lines = [
            "🧠 <b>Memory Orchestrator</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━",
            f"📊 Total RSS: <b>{rss_mb:.1f} MB</b>",
            f"📦 Modules: <b>{stats['loaded_count']}/{stats['total_count']}</b> loaded",
            f"🗑️ Unload TTL: <b>{stats['unload_ttl_sec'] // 60} min</b>",
            "",
        ]

        for mod in stats["modules"]:
            name_short = mod["name"].replace("modules.", "")
            if mod["state"] == "loaded":
                if mod["tier"] == "always_on":
                    icon = "🟢"
                    tier_label = "always-on"
                else:
                    ago = time.time() - mod["last_used"]
                    if ago < 60:
                        ago_str = f"{int(ago)}s ago"
                    else:
                        ago_str = f"{int(ago // 60)}m ago"
                    icon = "🔵"
                    tier_label = f"on-demand, {ago_str}"
                delta_kb = mod["rss_delta_bytes"] // 1024
                delta_str = f" +{delta_kb}KB" if delta_kb > 0 else ""
                lines.append(f"  {icon} <b>{name_short}</b> ({tier_label}){delta_str}")
            else:
                lines.append(f"  ⏸️ {name_short}")

        return "\n".join(lines)

    @staticmethod
    def _get_process_rss() -> int:
        """Get current process RSS in bytes."""
        try:
            return psutil.Process(os.getpid()).memory_info().rss
        except Exception:
            return 0
