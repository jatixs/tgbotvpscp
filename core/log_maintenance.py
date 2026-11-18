"""Retention for rotated application logs, independent of module unloading."""

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

LOG_PREFIXES = {"bot": "bot", "watchdog": "watchdog", "node": "node"}
ROTATED_SUFFIX = re.compile(r"(?:\d{4}-\d{2}-\d{2}|[1-9]\d*)(?:\.gz)?\Z")
CLEANUP_INTERVAL = 6 * 3600
RETRY_INTERVAL = 5 * 60


@dataclass
class CleanupResult:
    deleted: int = 0
    errors: int = 0


def cleanup_old_logs(log_root: str | Path, max_days: int = 7, *, now: float | None = None) -> CleanupResult:
    """Prune known rotated logs by mtime; preserve active logs, backups and links.

    Only direct children of bot/, watchdog/ and node/ are considered. Supported
    suffixes are YYYY-MM-DD and positive rotation numbers, optionally with .gz.
    A file exactly on the retention boundary is kept.
    """
    if max_days <= 0:
        raise ValueError("Log retention must be positive")
    cutoff = (time.time() if now is None else now) - max_days * 86400
    result = CleanupResult()
    for folder, prefix in LOG_PREFIXES.items():
        directory = Path(log_root) / folder
        if directory.is_symlink():
            continue
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    stem = f"{prefix}.log."
                    if not entry.name.startswith(stem) or not ROTATED_SUFFIX.fullmatch(entry.name[len(stem):]):
                        continue
                    try:
                        if entry.is_file(follow_symlinks=False) and entry.stat(follow_symlinks=False).st_mtime < cutoff:
                            os.remove(entry.path)
                            result.deleted += 1
                    except FileNotFoundError:
                        pass  # Rotation or another cleanup already removed this file.
                    except OSError as exc:
                        result.errors += 1
                        logging.warning("Could not remove rotated log %s: %s", entry.path, exc)
        except FileNotFoundError:
            pass
        except OSError as exc:
            result.errors += 1
            logging.warning("Could not scan log directory %s: %s", directory, exc)
    if result.deleted or result.errors:
        logging.info("Log cleanup: %d removed, %d errors (retention: %d days)",
                     result.deleted, result.errors, max_days)
    return result


async def maintain_logs(log_root: str | Path, max_days: int) -> None:
    """Run once at startup, then periodically; cancellation belongs to the caller."""
    if max_days <= 0:
        raise ValueError("Log retention must be positive")
    while True:
        delay = CLEANUP_INTERVAL
        try:
            result = await asyncio.to_thread(cleanup_old_logs, log_root, max_days)
            if result.errors:
                delay = RETRY_INTERVAL
        except Exception:
            logging.exception("Log maintenance failed; retrying in %s seconds", RETRY_INTERVAL)
            delay = RETRY_INTERVAL
        await asyncio.sleep(delay)
