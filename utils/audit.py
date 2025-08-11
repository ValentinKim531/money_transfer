from datetime import datetime
from typing import Optional, Any
import json
import sqlite3
import threading
import os
from pathlib import Path

DATA_DIR = Path(os.getenv("DATA_DIR", "./data")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
_AUDIT_DB = str(DATA_DIR / "audit_log.sqlite")

_lock = threading.Lock()


def _ensure_schema():
    with sqlite3.connect(_AUDIT_DB) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                user_id TEXT,
                operation_type TEXT,
                operation_target TEXT,
                details TEXT,
                status TEXT,
                error_message TEXT
            )
        """
        )
        conn.commit()


_ensure_schema()


def audit_write(
    user_id: Optional[str],
    operation_type: str,
    operation_target: str,
    details: Any,
    status: str,
    error_message: Optional[str] = None,
):
    record = (
        datetime.utcnow().isoformat(),
        user_id,
        operation_type,
        operation_target,
        json.dumps(details, ensure_ascii=False),
        status,
        error_message,
    )
    with _lock:
        with sqlite3.connect(_AUDIT_DB) as conn:
            conn.execute(
                """
            INSERT INTO audit_log(ts, user_id, operation_type, operation_target, details, status, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                record,
            )
            conn.commit()
