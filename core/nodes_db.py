import json
import logging
import secrets
import time
import os
import hashlib
from tortoise import Tortoise
from .models import Node
from .config import CONFIG_DIR, NODE_OFFLINE_TIMEOUT, TORTOISE_ORM

LEGACY_JSON_PATH = os.path.join(CONFIG_DIR, "nodes.json")


def _coerce_float(value, default: float = 0.0) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return default


def _build_default_availability_state(now: float) -> dict:
    return {
        "status": "unknown",
        "status_since": now,
        "tracking_since": now,
        "total_online_seconds": 0.0,
        "total_downtime_seconds": 0.0,
        "total_internet_downtime_seconds": 0.0,
        "total_physical_downtime_seconds": 0.0,
        "current_downtime_started_at": 0.0,
        "current_downtime_kind": "",
        "last_downtime_at": 0.0,
        "last_downtime_recovered_at": 0.0,
        "last_internet_downtime_at": 0.0,
        "last_physical_downtime_at": 0.0,
        "last_reboot_at": 0.0,
        "last_boot_time": 0.0,
    }


def _normalize_availability_state(raw_state, *, now: float) -> dict:
    state = _build_default_availability_state(now)
    if isinstance(raw_state, dict):
        state.update(raw_state)

    for key in (
        "status_since",
        "tracking_since",
        "total_online_seconds",
        "total_downtime_seconds",
        "total_internet_downtime_seconds",
        "total_physical_downtime_seconds",
        "current_downtime_started_at",
        "last_downtime_at",
        "last_downtime_recovered_at",
        "last_internet_downtime_at",
        "last_physical_downtime_at",
        "last_reboot_at",
        "last_boot_time",
    ):
        state[key] = _coerce_float(state.get(key), 0.0)

    if state.get("status") not in {"unknown", "online", "offline"}:
        state["status"] = "unknown"

    if not state["tracking_since"]:
        state["tracking_since"] = now

    return state


def _detect_reboot(prev_stats: dict, current_stats: dict, availability_state: dict) -> tuple[bool, float]:
    prev_boot_time = _coerce_float((prev_stats or {}).get("boot_time"), 0.0)
    current_boot_time = _coerce_float((current_stats or {}).get("boot_time"), 0.0)
    last_boot_time = _coerce_float(availability_state.get("last_boot_time"), 0.0)

    if prev_boot_time and current_boot_time and abs(current_boot_time - prev_boot_time) > 1:
        return True, current_boot_time

    if last_boot_time and current_boot_time and abs(current_boot_time - last_boot_time) > 1:
        return True, current_boot_time

    prev_uptime = _coerce_float((prev_stats or {}).get("uptime"), 0.0)
    current_uptime = _coerce_float((current_stats or {}).get("uptime"), 0.0)
    if prev_uptime > 0 and current_uptime > 0 and current_uptime + 60 < prev_uptime:
        return True, max(0.0, time.time() - current_uptime)

    return False, 0.0


def _get_token_hash(token: str) -> str:
    if not token:
        return ""
    return hashlib.sha256(token.encode()).hexdigest()


async def init_db():
    await Tortoise.init(config=TORTOISE_ORM)
    await Tortoise.generate_schemas()
    logging.info(f"ORM initialized. DB: {TORTOISE_ORM['connections']['default']}")
    await _ensure_billing_columns()
    await _migrate_from_json_if_needed()


async def _ensure_billing_columns():
    """Add billing-related columns to the nodes table if they are missing."""
    conn = Tortoise.get_connection("default")
    try:
        rows = await conn.execute_query("PRAGMA table_info(nodes)")
        existing = {row["name"] for row in rows[1]} if rows[1] else set()
    except Exception:
        return

    migrations = [
        ("is_cloud", "BOOL NOT NULL DEFAULT 0"),
        ("provider_name", "VARCHAR(100) NULL"),
        ("next_payment_date", "TIMESTAMP NULL"),
        ("billing_amount", "REAL NULL"),
        ("currency", "VARCHAR(10) NOT NULL DEFAULT '$'"),
        ("reminder_enabled", "BOOL NOT NULL DEFAULT 0"),
    ]

    for col_name, col_def in migrations:
        if col_name not in existing:
            try:
                await conn.execute_query(
                    f"ALTER TABLE nodes ADD COLUMN {col_name} {col_def}"
                )
                logging.info(f"✅ Added column '{col_name}' to nodes table.")
            except Exception as e:
                logging.warning(f"Column '{col_name}' migration skipped: {e}")


async def _migrate_from_json_if_needed():
    if not os.path.exists(LEGACY_JSON_PATH):
        return
    logging.info("♻️ Starting migration from nodes.json to Encrypted DB...")
    try:
        with open(LEGACY_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not data:
            return
        count = 0
        for token, node_data in data.items():
            t_hash = _get_token_hash(token)
            if await Node.exists(token_hash=t_hash):
                continue
            await Node.create(
                token_hash=t_hash,
                token_safe=token,
                name=node_data.get("name", "Unknown"),
                ip=node_data.get("ip", "Unknown"),
                created_at=node_data.get("created_at", time.time()),
                last_seen=node_data.get("last_seen", 0),
                stats=node_data.get("stats", {}),
                history=node_data.get("history", []),
                tasks=node_data.get("tasks", []),
                extra_state={},
            )
            count += 1
        os.rename(LEGACY_JSON_PATH, LEGACY_JSON_PATH + ".bak")
        logging.info(f"✅ Migration successful! Securely imported {count} nodes.")
    except Exception as e:
        logging.error(f"❌ CRITICAL: Migration failed: {e}", exc_info=True)


async def get_all_nodes():
    nodes = await Node.all()
    result = {}
    for node in nodes:
        real_token = node.token_safe or "ErrorDecryption"
        result[real_token] = {
            "token": real_token,
            "name": node.name,
            "created_at": node.created_at,
            "last_seen": node.last_seen,
            "ip": node.ip,
            "stats": node.stats,
            "tasks": node.tasks,
            "history": node.history,
            "provider_name": getattr(node, "provider_name", None),
            "is_cloud": getattr(node, "is_cloud", False),
            "billing_amount": getattr(node, "billing_amount", None),
            "currency": getattr(node, "currency", "$"),
            "next_payment_date": getattr(node, "next_payment_date", None),
            "reminder_enabled": getattr(node, "reminder_enabled", False),
            **node.extra_state,
        }
    return result


async def get_node_by_token(token: str):
    t_hash = _get_token_hash(token)
    node = await Node.get_or_none(token_hash=t_hash)
    if node:
        base = {
            "token": node.token_safe,
            "name": node.name,
            "created_at": node.created_at,
            "last_seen": node.last_seen,
            "ip": node.ip,
            "stats": node.stats,
            "tasks": node.tasks,
            "history": node.history,
            "provider_name": getattr(node, "provider_name", None),
            "is_cloud": getattr(node, "is_cloud", False),
            "billing_amount": getattr(node, "billing_amount", None),
            "currency": getattr(node, "currency", "$"),
            "next_payment_date": getattr(node, "next_payment_date", None),
            "reminder_enabled": getattr(node, "reminder_enabled", False),
        }
        return {**base, **node.extra_state}
    return None


async def create_node(name: str) -> str:
    raw_token = secrets.token_hex(16)
    await Node.create(
        token_hash=_get_token_hash(raw_token),
        token_safe=raw_token,
        name=name,
        ip="Unknown",
    )
    logging.info(f"Created new encrypted node: {name}")
    return raw_token


async def update_node_name(token: str, new_name: str):
    t_hash = _get_token_hash(token)
    node = await Node.get_or_none(token_hash=t_hash)
    if node:
        node.name = new_name
        await node.save(update_fields=["name"])
        logging.info(f"Node renamed to: {new_name}")
        return True
    return False


async def delete_node(token: str):
    t_hash = _get_token_hash(token)
    await Node.filter(token_hash=t_hash).delete()
    logging.info(f"Node deleted.")


async def update_node_heartbeat(token: str, ip: str, stats: dict):
    t_hash = _get_token_hash(token)
    node = await Node.get_or_none(token_hash=t_hash)
    if not node:
        return
    now = time.time()
    prev_last_seen = _coerce_float(node.last_seen, 0.0)
    prev_stats = node.stats or {}
    extra = node.extra_state or {}
    availability = _normalize_availability_state(
        extra.get("availability"),
        now=_coerce_float(node.created_at, now) or now,
    )
    offline_gap_detected = prev_last_seen > 0 and (now - prev_last_seen) >= NODE_OFFLINE_TIMEOUT

    reboot_detected, reboot_at = _detect_reboot(prev_stats, stats, availability)
    current_boot_time = _coerce_float(stats.get("boot_time"), 0.0)
    if reboot_detected and reboot_at:
        availability["last_reboot_at"] = reboot_at
    if current_boot_time:
        availability["last_boot_time"] = current_boot_time

    if availability.get("status") == "offline" or offline_gap_detected:
        if availability.get("status") == "online":
            status_since = _coerce_float(availability.get("status_since"), prev_last_seen)
            availability["total_online_seconds"] += max(0.0, prev_last_seen - status_since)
        downtime_started_at = (
            _coerce_float(availability.get("current_downtime_started_at"), 0.0)
            or (_coerce_float(availability.get("status_since"), 0.0) if availability.get("status") == "offline" else 0.0)
            or prev_last_seen
            or now
        )
        downtime_seconds = max(0.0, now - downtime_started_at)
        downtime_kind = "physical" if reboot_detected else "internet"

        # Ignore short gaps (< 60s) if there was no OS reboot
        if downtime_seconds >= 60.0 or downtime_kind == "physical":
            availability["total_downtime_seconds"] += downtime_seconds
            if downtime_kind == "physical":
                availability["total_physical_downtime_seconds"] += downtime_seconds
                availability["last_physical_downtime_at"] = downtime_started_at
            else:
                availability["total_internet_downtime_seconds"] += downtime_seconds
                availability["last_internet_downtime_at"] = downtime_started_at

            availability["last_downtime_at"] = downtime_started_at
        
        availability["last_downtime_recovered_at"] = now
        availability["current_downtime_started_at"] = 0.0
        availability["current_downtime_kind"] = downtime_kind

        availability["status"] = "online"
        availability["status_since"] = now
    elif availability.get("status") != "online":
        availability["status"] = "online"
        availability["status_since"] = now

    history = node.history or []
    point = {
        "t": int(now),
        "c": stats.get("cpu", 0),
        "r": stats.get("ram", 0),
        "rx": stats.get("net_rx", 0),
        "tx": stats.get("net_tx", 0),
    }
    history.append(point)
    if len(history) > 60:
        history = history[-60:]
    extra["availability"] = availability
    node.last_seen = now
    node.ip = ip
    node.stats = stats
    node.history = history
    node.extra_state = extra
    await node.save(update_fields=["last_seen", "ip", "stats", "history", "extra_state"])


async def reset_node_availability(token: str) -> bool:
    t_hash = _get_token_hash(token)
    node = await Node.get_or_none(token_hash=t_hash)
    if not node:
        return False

    now = time.time()
    extra = node.extra_state or {}
    
    # Reset all counters but maintain current status
    availability = extra.get("availability", {})
    current_status = availability.get("status", "unknown")
    
    new_availability = _build_default_availability_state(now)
    new_availability["status"] = current_status
    if current_status != "unknown":
        new_availability["status_since"] = now
    
    if node.stats:
        current_boot_time = _coerce_float(node.stats.get("boot_time"), 0.0)
        if current_boot_time:
            new_availability["last_boot_time"] = current_boot_time
            new_availability["last_reboot_at"] = current_boot_time
            
    extra["availability"] = new_availability
    node.extra_state = extra
    await node.save(update_fields=["extra_state"])
    return True


async def mark_node_offline(token: str, offline_at: float | None = None):
    t_hash = _get_token_hash(token)
    node = await Node.get_or_none(token_hash=t_hash)
    if not node:
        return False

    now = _coerce_float(offline_at, time.time()) or time.time()
    extra = node.extra_state or {}
    availability = _normalize_availability_state(
        extra.get("availability"),
        now=_coerce_float(node.created_at, now) or now,
    )

    if availability.get("status") != "offline":
        if availability.get("status") == "online":
            status_since = _coerce_float(availability.get("status_since"), now)
            availability["total_online_seconds"] += max(0.0, now - status_since)

        availability["status"] = "offline"
        availability["status_since"] = now
        availability["current_downtime_started_at"] = now
        availability["current_downtime_kind"] = ""
        availability["last_downtime_at"] = now

        extra["availability"] = availability
        node.extra_state = extra
        await node.save(update_fields=["extra_state"])

    return True


async def update_node_task(token: str, task: dict):
    t_hash = _get_token_hash(token)
    node = await Node.get_or_none(token_hash=t_hash)
    if node:
        tasks = node.tasks or []
        tasks.append(task)
        node.tasks = tasks
        await node.save(update_fields=["tasks"])


async def clear_node_tasks(token: str):
    t_hash = _get_token_hash(token)
    node = await Node.get_or_none(token_hash=t_hash)
    if node:
        node.tasks = []
        await node.save(update_fields=["tasks"])


async def update_node_extra(token: str, key: str, value):
    t_hash = _get_token_hash(token)
    node = await Node.get_or_none(token_hash=t_hash)
    if node:
        extra = node.extra_state or {}
        extra[key] = value
        node.extra_state = extra
        await node.save(update_fields=["extra_state"])
