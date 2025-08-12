import os, time, json, sqlite3, threading
from datetime import datetime
from typing import Optional, Any

_LOCK = threading.Lock()

BASE_DIR = os.getenv(
    "DATA_DIR",
    os.path.join(os.path.dirname(__file__), "..", "money_transfer", "data"),
)
os.makedirs(BASE_DIR, exist_ok=True)
_AUDIT_DB = os.path.join(BASE_DIR, "audit_log.sqlite")

_INITIALIZED = False

def _connect():
    # увеличим таймаут ожидания блокировки
    return sqlite3.connect(_AUDIT_DB, timeout=30)

def _ensure_schema():
    global _INITIALIZED
    if _INITIALIZED:
        return
    with _LOCK:
        if _INITIALIZED:
            return
        for attempt in range(10):
            try:
                with _connect() as conn:
                    # можно включать WAL, но это тоже берёт lock — делаем аккуратно
                    # conn.execute("PRAGMA journal_mode=WAL;")
                    conn.execute("""
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
                    """)
                    conn.commit()
                    _INITIALIZED = True
                    return
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower():
                    time.sleep(0.3)
                    continue
                raise
        # если прям совсем плохо — последний раз пробуем, иначе пусть падает
        with _connect() as conn:
            conn.execute("""
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
            """)
            conn.commit()
        _INITIALIZED = True

def audit_write(user_id: Optional[str], operation_type: str,
                operation_target: str, details: Any,
                status: str, error_message: Optional[str] = None):
    _ensure_schema()
    record = (
        datetime.utcnow().isoformat(),
        user_id, operation_type, operation_target,
        json.dumps(details, ensure_ascii=False),
        status, error_message
    )
    with _LOCK:
        with _connect() as conn:
            conn.execute("""
                INSERT INTO audit_log(ts, user_id, operation_type, operation_target, details, status, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, record)
            conn.commit()