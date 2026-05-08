"""
backend/alembic/env.py — Alembic migration environment.

Reads DATABASE_URL from environment (same logic as app/db.py).
Falls back to a SQLite URL for local testing when DATABASE_URL is not set.

Usage:
  cd backend/
  alembic upgrade head          # apply all migrations
  alembic revision --autogenerate -m "add my table"   # generate new migration
  alembic downgrade -1          # roll back one step
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

# ── Alembic config object (gives access to alembic.ini values) ────────────────
config = context.config

# ── Logging (as configured in alembic.ini) ────────────────────────────────────
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── Target metadata ───────────────────────────────────────────────────────────
# If you later add SQLAlchemy ORM models, import Base.metadata here:
#   from app.models import Base
#   target_metadata = Base.metadata
target_metadata = None

# ── Database URL resolution ───────────────────────────────────────────────────

def _get_url() -> str:
    """
    Resolve database URL:
    1. DATABASE_URL env var (PostgreSQL in production / CI)
    2. Fallback: SQLite at the same path used by app/db.py
    """
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("postgres://"):
        # SQLAlchemy requires postgresql:// not postgres://
        url = url.replace("postgres://", "postgresql://", 1)
    if url.startswith("postgresql://"):
        return url

    # SQLite fallback (mirrors config.py default)
    from pathlib import Path
    project_root = Path(__file__).resolve().parents[2]
    sqlite_path = os.environ.get(
        "DB_PATH",
        str(project_root / "backend" / "app" / "chishenme.db"),
    )
    return f"sqlite:///{sqlite_path}"


# ── Offline migration (generates SQL without connecting) ──────────────────────

def run_migrations_offline() -> None:
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online migration (connects to DB and runs migrations) ────────────────────

def run_migrations_online() -> None:
    url = _get_url()

    # Override sqlalchemy.url from alembic.ini with the resolved URL
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = url

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
