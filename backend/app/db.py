"""
backend/app/db.py — Unified database layer for Teller backend.

Auto-detects backend at startup:
  - If DATABASE_URL env var is set AND starts with "postgres://" or "postgresql://",
    use PostgreSQL via psycopg2.
  - Otherwise, fall back to SQLite (default for local dev and tests).

Public interface (unchanged for callers):
  init_db()      → create tables / run migrations
  tx()           → context manager yielding a connection-like object
  utc_now_iso()  → current UTC timestamp as ISO 8601 string
"""

import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from .config import settings

# ─── Backend detection ────────────────────────────────────────────────────────

_DATABASE_URL: str | None = os.environ.get("DATABASE_URL")

def _use_postgres() -> bool:
    """Return True when DATABASE_URL is set and points to PostgreSQL."""
    return bool(
        _DATABASE_URL
        and (_DATABASE_URL.startswith("postgres://") or _DATABASE_URL.startswith("postgresql://"))
    )


# ─── Shared utilities ─────────────────────────────────────────────────────────

def utc_now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(UTC).isoformat()


# ═══════════════════════════════════════════════════════════════════════════════
# SQLite backend (default / local dev / tests)
# ═══════════════════════════════════════════════════════════════════════════════

def _sqlite_conn() -> sqlite3.Connection:
    db_path = Path(settings.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=5, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _sqlite_init_db() -> None:
    with _sqlite_conn() as conn:
        conn.executescript(
            """
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
            """
        )
        # Idempotent column migrations
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(subscriptions)").fetchall()
        }
        if "source" not in columns:
            conn.execute("ALTER TABLE subscriptions ADD COLUMN source TEXT NOT NULL DEFAULT 'local'")
        if "product_id" not in columns:
            conn.execute("ALTER TABLE subscriptions ADD COLUMN product_id TEXT")
        if "expires_at" not in columns:
            conn.execute("ALTER TABLE subscriptions ADD COLUMN expires_at TEXT")


@contextmanager
def _sqlite_tx():
    """SQLite transaction context manager — yields a sqlite3.Connection."""
    conn = _sqlite_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# PostgreSQL backend
# ═══════════════════════════════════════════════════════════════════════════════

# Deferred import so psycopg2 is only required when actually using PG.
# Tests that run against SQLite never need psycopg2 installed.

_INIT_SQL_PG = """
CREATE TABLE IF NOT EXISTS users (
    id          SERIAL PRIMARY KEY,
    user_id     TEXT    NOT NULL UNIQUE,
    password_hash TEXT  NOT NULL,
    created_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS subscriptions (
    user_id     TEXT PRIMARY KEY,
    plan        TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'local',
    product_id  TEXT,
    expires_at  TEXT,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_quotas (
    user_id     TEXT NOT NULL,
    quota_date  TEXT NOT NULL,
    left_count  INTEGER NOT NULL,
    PRIMARY KEY (user_id, quota_date)
);

CREATE TABLE IF NOT EXISTS orders (
    order_no    TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    plan        TEXT NOT NULL,
    amount      NUMERIC(10,4) NOT NULL,
    status      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    paid_at     TEXT
);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    id            SERIAL PRIMARY KEY,
    user_id       TEXT NOT NULL,
    endpoint      TEXT NOT NULL,
    idem_key      TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    UNIQUE (user_id, endpoint, idem_key)
);
"""

_MIGRATIONS_PG = [
    "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'local'",
    "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS product_id TEXT",
    "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS expires_at TEXT",
]

# Known INSERT OR REPLACE / INSERT OR IGNORE → PostgreSQL ON CONFLICT rewrites
_UPSERT_MAP: dict[str, str] = {
    # subscriptions upsert (alipay notify + revenuecat webhook)
    "INSERT INTO subscriptions (user_id, plan, source, product_id, expires_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s)": (
        "INSERT INTO subscriptions (user_id, plan, source, product_id, expires_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (user_id) DO UPDATE SET "
        "plan=EXCLUDED.plan, source=EXCLUDED.source, product_id=EXCLUDED.product_id, "
        "expires_at=EXCLUDED.expires_at, updated_at=EXCLUDED.updated_at"
    ),
    # idempotency_keys upsert
    "INSERT INTO idempotency_keys (user_id, endpoint, idem_key, response_json, created_at) VALUES (%s, %s, %s, %s, %s)": (
        "INSERT INTO idempotency_keys (user_id, endpoint, idem_key, response_json, created_at) "
        "VALUES (%s, %s, %s, %s, %s) "
        "ON CONFLICT (user_id, endpoint, idem_key) DO UPDATE SET "
        "response_json=EXCLUDED.response_json, created_at=EXCLUDED.created_at"
    ),
    # subscriptions INSERT OR IGNORE (registration)
    "INSERT INTO subscriptions (user_id, plan, source, updated_at) VALUES (%s, %s, %s, %s)": (
        "INSERT INTO subscriptions (user_id, plan, source, updated_at) "
        "VALUES (%s, %s, %s, %s) "
        "ON CONFLICT (user_id) DO NOTHING"
    ),
}


class _PgConnShim:
    """
    Wraps a psycopg2 connection + cursor to expose the same API as sqlite3.Connection:
      conn.execute(sql, params) → cursor
      cursor.fetchone()         → dict-like row  (RealDictRow)
      cursor.fetchall()         → list[dict]

    Also translates:
      - SQLite ? placeholders → %s
      - INSERT OR REPLACE / INSERT OR IGNORE → ON CONFLICT … equivalents
    """

    def __init__(self, conn) -> None:
        self._conn = conn
        self._cur = conn.cursor()

    @staticmethod
    def _adapt_sql(sql: str) -> str:
        """Convert SQLite ? placeholders to psycopg2 %s."""
        return re.sub(r"\?", "%s", sql)

    @staticmethod
    def _strip_sqlite_modifiers(sql: str) -> str:
        """Remove INSERT OR REPLACE / INSERT OR IGNORE modifiers."""
        sql = re.sub(r"INSERT\s+OR\s+REPLACE\s+INTO\s+(\w+)",
                     lambda m: f"INSERT INTO {m.group(1)}", sql, flags=re.IGNORECASE)
        sql = re.sub(r"INSERT\s+OR\s+IGNORE\s+INTO\s+(\w+)",
                     lambda m: f"INSERT INTO {m.group(1)}", sql, flags=re.IGNORECASE)
        return sql

    def execute(self, sql: str, params: tuple = ()):
        adapted = self._adapt_sql(sql)
        adapted = self._strip_sqlite_modifiers(adapted)
        adapted = _UPSERT_MAP.get(adapted.strip(), adapted)
        self._cur.execute(adapted, params or ())
        return self._cur

    def executemany(self, sql: str, seq: list) -> None:
        adapted = self._adapt_sql(sql)
        adapted = self._strip_sqlite_modifiers(adapted)
        self._cur.executemany(adapted, seq)

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self) -> list:
        return self._cur.fetchall()

    # Support `with conn:` (no-op — tx() manages the transaction)
    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


def _pg_get_connection():
    import psycopg2
    import psycopg2.extras

    conn = psycopg2.connect(
        _DATABASE_URL,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    conn.autocommit = False
    return conn


def _pg_init_db() -> None:
    conn = _pg_get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(_INIT_SQL_PG)
            for stmt in _MIGRATIONS_PG:
                cur.execute(stmt)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def _pg_tx() -> Iterator[_PgConnShim]:
    """PostgreSQL transaction context manager — yields a _PgConnShim."""
    conn = _pg_get_connection()
    shim = _PgConnShim(conn)
    try:
        yield shim
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# Public API — callers use only these three names
# ═══════════════════════════════════════════════════════════════════════════════

def init_db() -> None:
    """Create tables and run lightweight schema migrations."""
    if _use_postgres():
        _pg_init_db()
    else:
        _sqlite_init_db()


@contextmanager
def tx():
    """
    Context manager that yields a connection-like object.

    SQLite mode  → yields sqlite3.Connection (same as before)
    Postgres mode → yields _PgConnShim (same .execute() / .fetchone() / .fetchall() API)

    Usage (unchanged across both backends):
        with tx() as conn:
            row = conn.execute("SELECT ...", (param,)).fetchone()
    """
    if _use_postgres():
        with _pg_tx() as conn:
            yield conn
    else:
        with _sqlite_tx() as conn:
            yield conn
