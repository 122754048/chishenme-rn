import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .config import settings


def _conn() -> sqlite3.Connection:
    db_path = Path(settings.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=5, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def init_db() -> None:
    with _conn() as conn:
        conn.executescript(
            '''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id TEXT PRIMARY KEY,
                plan TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'local',
                product_id TEXT,
                expires_at TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS daily_quotas (
                user_id TEXT NOT NULL,
                quota_date TEXT NOT NULL,
                left_count INTEGER NOT NULL,
                PRIMARY KEY(user_id, quota_date)
            );

            CREATE TABLE IF NOT EXISTS orders (
                order_no TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                plan TEXT NOT NULL,
                amount REAL NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                paid_at TEXT
            );

            CREATE TABLE IF NOT EXISTS idempotency_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                idem_key TEXT NOT NULL,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, endpoint, idem_key)
            );
            '''
        )
        columns = {
            row['name']
            for row in conn.execute('PRAGMA table_info(subscriptions)').fetchall()
        }
        if 'source' not in columns:
            conn.execute("ALTER TABLE subscriptions ADD COLUMN source TEXT NOT NULL DEFAULT 'local'")
        if 'product_id' not in columns:
            conn.execute('ALTER TABLE subscriptions ADD COLUMN product_id TEXT')
        if 'expires_at' not in columns:
            conn.execute('ALTER TABLE subscriptions ADD COLUMN expires_at TEXT')


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@contextmanager
def tx():
    conn = _conn()
    try:
        conn.execute('BEGIN IMMEDIATE')
        yield conn
        conn.execute('COMMIT')
    except Exception:
        conn.execute('ROLLBACK')
        raise
    finally:
        conn.close()
