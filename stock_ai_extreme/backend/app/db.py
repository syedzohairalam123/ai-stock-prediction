"""
Phase 3 — database engine and session management.

SQLite by default (zero setup — the whole point of a demo/educational app
being runnable with no external services). Swapping DATABASE_URL to a
Postgres URL later needs no code changes anywhere else in the app.
"""
from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings
from .logging_config import get_logger

logger = get_logger("neural_market.db")


class Base(DeclarativeBase):
    pass


def _make_engine():
    connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    return create_engine(settings.database_url, connect_args=connect_args)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


# ---------------------------------------------------------------------------
# Phase 10 — async session support for the AI assistant (SQLite via aiosqlite,
# PostgreSQL via asyncpg). The rest of the app continues to use the sync
# engine above; this is purely additive.
# ---------------------------------------------------------------------------

def _make_async_url(url: str) -> str:
    """Translate the configured DATABASE_URL into an async-compatible URL."""
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    if url.startswith("sqlite://"):
        return url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


def _async_connect_args() -> dict:
    """SQLite-specific connect args for the async engine."""
    if settings.database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


async_engine = create_async_engine(
    _make_async_url(settings.database_url),
    pool_pre_ping=True,
    connect_args=_async_connect_args(),
)
AsyncSessionLocal = async_sessionmaker(
    async_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
)


def _scalar_default_sql(column) -> str | None:
    """SQL literal for a column's scalar Python-side default, or None.

    Only used when back-filling a column onto an existing table, where the
    existing rows need *something*. Callables (like ``_utcnow``) are skipped:
    the correct value for a historical row is not knowable from a function.
    """
    default = column.default
    if default is None or getattr(default, "is_callable", False):
        return None
    value = getattr(default, "arg", None)
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        escaped = value.replace("'", "''")
        return f"'{escaped}'"
    return None


def _ensure_additive_columns() -> list[str]:
    """Add model columns that are missing from the physical tables.

    ``create_all`` creates missing *tables* but never alters existing ones, so
    a database created before a schema addition would keep working until the
    first query touched a new column and then fail with "no such column". This
    performs the narrow, safe subset of a migration that is genuinely needed
    here: append-only ``ALTER TABLE ... ADD COLUMN`` for columns that are new.

    Deliberately conservative — it never drops, renames, retypes or back-fills
    a column, and it skips a non-nullable column it cannot supply a scalar
    default for rather than inventing values for existing rows. Anything more
    involved than this still belongs in a real migration tool (Alembic), which
    is the documented next step for this schema.
    """
    from . import models  # noqa: F401 (registers the models with Base.metadata)

    added: list[str] = []
    inspector = inspect(engine)
    preparer = engine.dialect.identifier_preparer

    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        existing = {col["name"] for col in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing:
                continue
            default_sql = _scalar_default_sql(column)
            if not column.nullable and default_sql is None:
                logger.warning(
                    "skipping non-nullable column %s.%s with no scalar default — "
                    "existing rows cannot be back-filled safely",
                    table.name, column.name,
                )
                continue
            ddl = (
                f"ALTER TABLE {preparer.quote(table.name)} "
                f"ADD COLUMN {preparer.quote(column.name)} {column.type.compile(dialect=engine.dialect)}"
            )
            if default_sql is not None:
                ddl += f" DEFAULT {default_sql}"
            try:
                with engine.begin() as conn:
                    conn.execute(text(ddl))
                added.append(f"{table.name}.{column.name}")
            except Exception as exc:  # one bad column must not block startup
                logger.warning("failed to add column %s.%s: %s", table.name, column.name, exc)

    if added:
        logger.info("schema migration: added %d column(s): %s", len(added), ", ".join(added))
    return added


def init_db() -> None:
    """Create tables if they don't exist yet, then apply the additive column
    migration for databases created by an earlier version of the schema.
    Deliberately not Alembic — for a schema this small, `create_all` plus
    append-only column additions is honest and sufficient; add Alembic
    migrations once the schema needs to evolve destructively."""
    from . import models  # noqa: F401 (import registers the models with Base.metadata)
    from .derivatives import models as derivatives_models  # Phase 16: derivatives models
    # Imported from the sub-package (not the package root) so registering the
    # tables does not drag the whole Phase 17 router/engine import chain in.
    from .breaking_news.models import models as breaking_news_models  # noqa: F401  Phase 17
    Base.metadata.create_all(bind=engine)
    _ensure_additive_columns()


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


@asynccontextmanager
async def async_session_scope():
    """Async equivalent of :func:`session_scope`.

    Used by the Phase 10 AI assistant backend so that ContextBuilder,
    ConversationService and AgentRouter can run real async SQLAlchemy queries
    against the same database without blocking the event loop.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
