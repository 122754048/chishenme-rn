"""Initial schema — create all Teller tables.

Revision ID: 0001_initial_schema
Revises: (none)
Create Date: 2026-05-06 00:00:00.000000 UTC

This migration creates the five core tables:
  users, subscriptions, daily_quotas, orders, idempotency_keys

It is designed to be idempotent (uses IF NOT EXISTS) so it is safe to run
against a database that was previously initialised via init_db().
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── users ──────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            SERIAL PRIMARY KEY,
            user_id       TEXT    NOT NULL UNIQUE,
            password_hash TEXT    NOT NULL,
            created_at    TEXT    NOT NULL
        )
    """)

    # ── subscriptions ──────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            user_id    TEXT PRIMARY KEY,
            plan       TEXT NOT NULL,
            source     TEXT NOT NULL DEFAULT 'local',
            product_id TEXT,
            expires_at TEXT,
            updated_at TEXT NOT NULL
        )
    """)

    # ── daily_quotas ───────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS daily_quotas (
            user_id    TEXT    NOT NULL,
            quota_date TEXT    NOT NULL,
            left_count INTEGER NOT NULL,
            PRIMARY KEY (user_id, quota_date)
        )
    """)

    # ── orders ─────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            order_no   TEXT           PRIMARY KEY,
            user_id    TEXT           NOT NULL,
            plan       TEXT           NOT NULL,
            amount     NUMERIC(10,4)  NOT NULL,
            status     TEXT           NOT NULL,
            created_at TEXT           NOT NULL,
            paid_at    TEXT
        )
    """)

    # ── idempotency_keys ───────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS idempotency_keys (
            id            SERIAL PRIMARY KEY,
            user_id       TEXT NOT NULL,
            endpoint      TEXT NOT NULL,
            idem_key      TEXT NOT NULL,
            response_json TEXT NOT NULL,
            created_at    TEXT NOT NULL,
            UNIQUE (user_id, endpoint, idem_key)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS idempotency_keys")
    op.execute("DROP TABLE IF EXISTS orders")
    op.execute("DROP TABLE IF EXISTS daily_quotas")
    op.execute("DROP TABLE IF EXISTS subscriptions")
    op.execute("DROP TABLE IF EXISTS users")
