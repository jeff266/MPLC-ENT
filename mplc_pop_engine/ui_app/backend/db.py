"""
DB engine/session setup.

SQLite for now (local-only, solo user). To move to Postgres later (data
team, concurrent access), change DB_URL below — nothing else in this
codebase needs to change, since models.py uses no SQLite-specific types.
"""

import os
from pathlib import Path
from contextlib import contextmanager

from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker, Session

_DEFAULT_DB_PATH = Path(__file__).parent / "pop_engine.db"
DB_URL = os.environ.get("POP_ENGINE_DB_URL", f"sqlite:///{_DEFAULT_DB_PATH}")

# check_same_thread=False only matters for SQLite; harmless no-op elsewhere
# via connect_args being SQLite-specific — guard it.
_connect_args = {"check_same_thread": False} if DB_URL.startswith("sqlite") else {}

engine = create_engine(DB_URL, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db():
    """Create all tables if they don't exist. Idempotent — safe to call
    on every app startup."""
    from . import models  # noqa: F401 (ensures models are registered)
    models.Base.metadata.create_all(bind=engine)
    _add_missing_columns()


def _add_missing_columns():
    """create_all() only creates MISSING TABLES -- it does nothing for a
    table that already exists but is missing a column a newer models.py
    added (e.g. Jeff's existing local pop_engine.db gaining ClayMatch.
    ai_verdict/ai_reasoning/ai_verified_at on 2026-11-16, added after his
    DB already had rows). There's no migration framework here (single-
    user local SQLite, per this file's own docstring), so this is the
    lightweight, additive-only substitute: for every mapped column not
    already present in the real table, `ALTER TABLE ... ADD COLUMN`.
    SQLite only supports adding nullable columns this way (no backfill,
    no constraints) -- which is exactly what every column added after the
    fact needs to be, so this is never used for anything else. Safe to
    run every startup: a column that already exists is simply skipped."""
    from . import models  # noqa: F401 (ensures models are registered)

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table in models.Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # just-created by create_all() above, already has every column
            existing_cols = {c["name"] for c in inspector.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing_cols:
                    continue
                col_type = col.type.compile(dialect=engine.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col_type}'))
                print(f"[db] Added missing column {table.name}.{col.name} to existing database.", flush=True)


@contextmanager
def get_session():
    """Context-manager session for use outside FastAPI's Depends (e.g. the
    pipeline-run script)."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db():
    """FastAPI dependency — yields a session, closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
