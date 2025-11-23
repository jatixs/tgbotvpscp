import aiosqlite
import json
import logging
import secrets
import time
import os
from .config import CONFIG_DIR

# Путь к файлу базы данных
DB_PATH = os.path.join(CONFIG_DIR, "nodes.db")

async def init_db():
    """Инициализация таблицы в SQLite."""
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

def _deserialize_node(row):
    """Собирает объект ноды из строки БД, объединяя основные поля и extra_state."""
    base = {
        "token": row['token'],
        "name": row['name'],
        "created_at": row['created_at'],
        "last_seen": row['last_seen'],
        "ip": row['ip'],
        "stats": json.loads(row['stats']) if row['stats'] else {},
        "history": json.loads(row['history']) if row['history'] else [],
        "tasks": json.loads(row['tasks']) if row['tasks'] else []
    }
    # extra_state хранит временные флаги вроде is_restarting, alerts и т.д.
    extra = json.loads(row['extra_state']) if row['extra_state'] else {}
    return {**base, **extra}

async def get_all_nodes():
    """Возвращает словарь всех нод."""
    nodes = {}
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM nodes") as cursor:
            async for row in cursor:
                nodes[row['token']] = _deserialize_node(row)
    return nodes

async def get_node_by_token(token: str):
    """Получает одну ноду по токену."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM nodes WHERE token = ?", (token,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return _deserialize_node(row)
    return None

async def create_node(name: str) -> str:
    """Создает новую ноду и возвращает токен."""
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
    """Удаляет ноду."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM nodes WHERE token = ?", (token,))
        await db.commit()
    logging.info(f"Node deleted: {token[:8]}...")

async def update_node_heartbeat(token: str, ip: str, stats: dict):
    """Обновляет статус ноды при получении хартбита."""
    # Сначала читаем историю, чтобы добавить точку
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT history FROM nodes WHERE token = ?", (token,)) as cursor:
            row = await cursor.fetchone()
            if not row: return
            history = json.loads(row['history']) if row['history'] else []
    
    point = {
        "t": int(time.time()),
        "c": stats.get("cpu", 0),
        "r": stats.get("ram", 0),
        "rx": stats.get("net_rx", 0),
        "tx": stats.get("net_tx", 0)
    }
    history.append(point)
    # Ограничиваем историю последними 60 точками для экономии места
    if len(history) > 60:
        history = history[-60:]
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE nodes SET last_seen = ?, ip = ?, stats = ?, history = ? WHERE token = ?",
            (time.time(), ip, json.dumps(stats), json.dumps(history), token)
        )
        await db.commit()

async def update_node_task(token: str, task: dict):
    """Добавляет задачу в очередь ноды."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT tasks FROM nodes WHERE token = ?", (token,)) as cursor:
            row = await cursor.fetchone()
            if not row: return
            tasks = json.loads(row['tasks']) if row['tasks'] else []
        
        tasks.append(task)
        await db.execute("UPDATE nodes SET tasks = ? WHERE token = ?", (json.dumps(tasks), token))
        await db.commit()

async def clear_node_tasks(token: str):
    """Очищает очередь задач ноды (после их отправки)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE nodes SET tasks = '[]' WHERE token = ?", (token,))
        await db.commit()

async def update_node_extra(token: str, key: str, value):
    """Обновляет поле в JSON-столбце extra_state (для флагов и алертов)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT extra_state FROM nodes WHERE token = ?", (token,)) as cursor:
            row = await cursor.fetchone()
            if not row: return
            state = json.loads(row['extra_state']) if row['extra_state'] else {}
        
        state[key] = value
        await db.execute("UPDATE nodes SET extra_state = ? WHERE token = ?", (json.dumps(state), token))
        await db.commit()