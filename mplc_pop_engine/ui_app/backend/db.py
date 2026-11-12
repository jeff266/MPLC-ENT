"""
DB engine/session setup.

SQLite for now (local-only, solo user). To move to Postgres later (data
team, concurrent access), change DB_URL below — nothing else in this
codebase needs to change, since models.py uses no SQLite-specific types.
"""

import os
from pathlib import Path
from contextlib import contextmanager

from sqlalchemy import create_engine
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
