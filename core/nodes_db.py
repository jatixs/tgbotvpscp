import aiosqlite
import json
import logging
import secrets
import time
import os
from .config import CONFIG_DIR

DB_PATH = os.path.join(CONFIG_DIR, "nodes.db")
LEGACY_JSON_PATH = os.path.join(CONFIG_DIR, "nodes.json")


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS nodes (
                token TEXT PRIMARY KEY,
                name TEXT,
                created_at REAL,
                last_seen REAL,
                ip TEXT,
                stats TEXT,
                history TEXT,
                tasks TEXT,
                extra_state TEXT
            )
        """)
        await db.commit()

    logging.info(f"Database initialized at {DB_PATH}")
    await _migrate_from_json_if_needed()


async def _migrate_from_json_if_needed():
    if not os.path.exists(LEGACY_JSON_PATH):
        return

    logging.info("Found legacy nodes.json. Starting migration to SQLite...")
    try:
        with open(LEGACY_JSON_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if not data:
            logging.info("nodes.json is empty. Skipping.")
            return

        async with aiosqlite.connect(DB_PATH) as db:
            count = 0
            for token, node in data.items():
                cursor = await db.execute("SELECT 1 FROM nodes WHERE token = ?", (token,))
                if await cursor.fetchone():
                    continue

                await db.execute(
                    "INSERT INTO nodes (token, name, created_at, last_seen, ip, stats, history, tasks, extra_state) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        token,
                        node.get("name", "Unknown"),
                        node.get("created_at", time.time()),
                        node.get("last_seen", 0),
                        node.get("ip", "Unknown"),
                        json.dumps(node.get("stats", {})),
                        json.dumps(node.get("history", [])),
                        json.dumps(node.get("tasks", [])),
                        "{}"
                    )
                )
                count += 1
            await db.commit()

        os.rename(LEGACY_JSON_PATH, LEGACY_JSON_PATH + ".bak")
        logging.info(
            f"Migration successful! Imported {count} nodes. Legacy file renamed to .bak")

    except Exception as e:
        logging.error(f"CRITICAL: Migration failed: {e}", exc_info=True)


def _deserialize_node(row, include_history=True):
    base = {
        "token": row['token'],
        "name": row['name'],
        "created_at": row['created_at'],
        "last_seen": row['last_seen'],
        "ip": row['ip'],
        "stats": json.loads(row['stats']) if row['stats'] else {},
        "tasks": json.loads(row['tasks']) if row['tasks'] else []
    }
    if include_history:
        base["history"] = json.loads(row['history']) if row['history'] else []
    
    extra = json.loads(row['extra_state']) if row['extra_state'] else {}
    return {**base, **extra}


async def get_all_nodes():
    nodes = {}
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        # Оптимизация RAM: НЕ выбираем history, так как она может быть большой и не нужна для листинга
        async with db.execute("SELECT token, name, created_at, last_seen, ip, stats, tasks, extra_state FROM nodes") as cursor:
            async for row in cursor:
                nodes[row['token']] = _deserialize_node(row, include_history=False)
    return nodes


async def get_node_by_token(token: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM nodes WHERE token = ?", (token,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return _deserialize_node(row, include_history=True)
    return None


async def create_node(name: str) -> str:
    token = secrets.token_hex(16)
    now = time.time()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO nodes (token, name, created_at, last_seen, ip, stats, history, tasks, extra_state) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (token, name, now, 0, "Unknown", "{}", "[]", "[]", "{}")
        )
        await db.commit()
    logging.info(f"Created new node: {name} (Token: {token[:8]}...)")
    return token


async def delete_node(token: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM nodes WHERE token = ?", (token,))
        await db.commit()
    safe_token = token.replace('\r\n', '').replace('\n', '').replace('\r', '')[:8]
    logging.info(f"Node deleted: {safe_token}...")


async def update_node_heartbeat(token: str, ip: str, stats: dict):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT history FROM nodes WHERE token = ?", (token,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return
            history = json.loads(row['history']) if row['history'] else []

    point = {
        "t": int(time.time()),
        "c": stats.get("cpu", 0),
        "r": stats.get("ram", 0),
        "rx": stats.get("net_rx", 0),
        "tx": stats.get("net_tx", 0)
    }
    history.append(point)
    if len(history) > 60:
        history = history[-60:]

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE nodes SET last_seen = ?, ip = ?, stats = ?, history = ? WHERE token = ?",
            (time.time(), ip, json.dumps(stats), json.dumps(history), token)
        )
        await db.commit()


async def update_node_task(token: str, task: dict):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT tasks FROM nodes WHERE token = ?", (token,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return
            tasks = json.loads(row['tasks']) if row['tasks'] else []

        tasks.append(task)
        await db.execute("UPDATE nodes SET tasks = ? WHERE token = ?", (json.dumps(tasks), token))
        await db.commit()


async def clear_node_tasks(token: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE nodes SET tasks = '[]' WHERE token = ?", (token,))
        await db.commit()


async def update_node_extra(token: str, key: str, value):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT extra_state FROM nodes WHERE token = ?", (token,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return
            state = json.loads(
                row['extra_state']) if row['extra_state'] else {}

        state[key] = value
        await db.execute("UPDATE nodes SET extra_state = ? WHERE token = ?", (json.dumps(state), token))
        await db.commit()