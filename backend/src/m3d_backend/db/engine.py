"""Async SQLAlchemy engine + session factory."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from m3d_backend.db.models import Base


def make_engine(db_url: str) -> AsyncEngine:
    """Create the async engine with WAL + sane SQLite pragmas.

    Pragmas applied via the connection lifecycle, not in the URL, so they survive
    reconnects.
    """
    engine = create_async_engine(
        db_url,
        echo=False,
        future=True,
        connect_args={"timeout": 30},
    )

    @_event_listener(engine)
    def _apply_pragmas(dbapi_conn: object, _conn_record: object) -> None:  # type: ignore[misc]
        cur = dbapi_conn.cursor()  # type: ignore[attr-defined]
        try:
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=5000")
        finally:
            cur.close()

    return engine


def _event_listener(engine: AsyncEngine):  # type: ignore[no-untyped-def]
    """Adapter so we can register a sync 'connect' listener on the AsyncEngine."""
    from sqlalchemy import event

    def decorator(func):  # type: ignore[no-untyped-def]
        event.listen(engine.sync_engine, "connect", func)
        return func

    return decorator


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db(engine: AsyncEngine) -> None:
    """Create tables if they don't exist. Used until Alembic migrations land in M2."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Async-generator session scope for FastAPI deps."""
    async with factory() as session:
        yield session
