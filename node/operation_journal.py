"""Durable command deduplication. Interrupted actions are never retried automatically."""
import json
import logging
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager


def open_journal(path):
    try:
        return OperationJournal(path)
    except (OSError, sqlite3.Error):
        logging.exception("Operation journal unavailable; reliable commands are paused")
        return None


def heartbeat_state(journal):
    if journal is None:
        return [], True
    try:
        return journal.reports(), False
    except (OSError, sqlite3.Error, ValueError):
        logging.exception("Cannot read operation journal; reliable commands are paused")
        return [], True


class OperationJournal:
    def __init__(self, path):
        self.path = str(path)
        # Pending results may include command output; restrict access before SQLite opens it.
        fd = os.open(self.path, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
        os.close(fd)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, status TEXT, result TEXT, updated REAL)")
            db.execute("CREATE INDEX IF NOT EXISTS operations_pending ON operations(updated) WHERE status != 'acknowledged'")
            db.execute("UPDATE operations SET status='unknown' WHERE status='running'")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def claim(self, operation_id):
        if not isinstance(operation_id, str) or uuid.UUID(operation_id).hex != operation_id:
            raise ValueError("Invalid operation ID")
        with self.connect() as db:
            changed = db.execute(
                "INSERT OR IGNORE INTO operations VALUES (?, 'running', NULL, ?)",
                (operation_id, time.time()),
            ).rowcount
        return bool(changed)

    def finish(self, operation_id, result=None, status="finished"):
        with self.connect() as db:
            db.execute("UPDATE operations SET status=?, result=?, updated=? WHERE id=? AND status='running'",
                       (status, json.dumps(result), time.time(), operation_id))

    def execute(self, task, command):
        operation_id = task.get("operation_id")
        if operation_id and not self.claim(operation_id):
            return
        try:
            command(task)
            if operation_id:
                self.finish(operation_id)
        except Exception as exc:
            if operation_id:
                self.finish(operation_id, {"error": str(exc)}, status="failed")
            raise

    def reports(self):
        with self.connect() as db:
            rows = db.execute(
                "SELECT id,status,result FROM operations WHERE status != 'acknowledged' "
                "ORDER BY CASE WHEN status='running' THEN 1 ELSE 0 END, updated LIMIT 100"
            ).fetchall()
        return [{"id": row[0], "status": row[1], "result": json.loads(row[2]) if row[2] else None} for row in rows]

    def acknowledge(self, ids):
        if not isinstance(ids, list):
            return
        with self.connect() as db:
            for operation_id in ids[:100]:
                if isinstance(operation_id, str):
                    db.execute("UPDATE operations SET status='acknowledged',result=NULL WHERE id=? AND status IN ('finished','failed','unknown')",
                               (operation_id,))
