"""
Phase 3 — database engine and session management.

SQLite by default (zero setup — the whole point of a demo/educational app
being runnable with no external services). Swapping DATABASE_URL to a
Postgres URL later needs no code changes anywhere else in the app.
"""
from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    return create_engine(settings.database_url, connect_args=connect_args)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    """Create tables if they don't exist yet. Deliberately not Alembic —
    for a schema this small, `create_all` is honest and sufficient; add
    Alembic migrations once the schema needs to evolve under real data."""
    from . import models  # noqa: F401 (import registers the models with Base.metadata)
    Base.metadata.create_all(bind=engine)


@contextmanager
def session_scope():
    """`with session_scope() as db: ...` — commits on success, rolls back
    and re-raises on any exception, always closes."""
    db: Session = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
