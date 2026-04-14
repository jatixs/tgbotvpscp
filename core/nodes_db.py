import json
import logging
import secrets
import time
import os
import hashlib
from tortoise import Tortoise
from .models import Node
from .config import CONFIG_DIR, TORTOISE_ORM

LEGACY_JSON_PATH = os.path.join(CONFIG_DIR, "nodes.json")


def _get_token_hash(token: str) -> str:
    if not token:
        return ""
    return hashlib.sha256(token.encode()).hexdigest()


async def init_db():
    await Tortoise.init(config=TORTOISE_ORM)
    await Tortoise.generate_schemas()
    logging.info(f"ORM initialized. DB: {TORTOISE_ORM['connections']['default']}")
    await _migrate_from_json_if_needed()


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
        await node.save()
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
    history = node.history or []
    point = {
        "t": int(time.time()),
        "c": stats.get("cpu", 0),
        "r": stats.get("ram", 0),
        "rx": stats.get("net_rx", 0),
        "tx": stats.get("net_tx", 0),
    }
    history.append(point)
    if len(history) > 60:
        history = history[-60:]
    node.last_seen = time.time()
    node.ip = ip
    node.stats = stats
    node.history = history
    await node.save()


async def update_node_task(token: str, task: dict):
    t_hash = _get_token_hash(token)
    node = await Node.get_or_none(token_hash=t_hash)
    if node:
        tasks = node.tasks or []
        tasks.append(task)
        node.tasks = tasks
        await node.save()


async def clear_node_tasks(token: str):
    t_hash = _get_token_hash(token)
    node = await Node.get_or_none(token_hash=t_hash)
    if node:
        node.tasks = []
        await node.save()


async def update_node_extra(token: str, key: str, value):
    t_hash = _get_token_hash(token)
    node = await Node.get_or_none(token_hash=t_hash)
    if node:
        extra = node.extra_state or {}
        extra[key] = value
        node.extra_state = extra
        await node.save()
