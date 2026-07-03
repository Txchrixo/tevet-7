"""Async SQLAlchemy setup for the Tevet-7 control-plane database.

This module manages the **control-plane** connection only — i.e. tenants,
users, configs, audit logs, quotas. Tenant *business* databases (e.g. Drive
Producteur's real DB) are connected to dynamically per-request via the
Connector abstraction (see ``app/connectors/base.py``).

Read-only connection to tenant databases will be created dynamically
per-tenant in Phase 1, using a separate engine pool with a read-only
Postgres role (or a read replica URL) configured per tenant in the
control plane.
"""

from __future__ import annotations

from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

# Module-level engine. Lazy-initialised on first use so tests can monkey-patch
# the URL via `get_settings.cache_clear()` before the first call.
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the singleton async engine for the control-plane DB.

    Pool settings are tuned for a small backend service. For higher concurrency
    bump `pool_size` and `max_overflow` or move to pgbouncer.
    """
    global _engine, _session_factory
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            echo=False,                # set True to log SQL (very noisy)
            pool_pre_ping=True,        # detect dropped connections
            pool_size=5,
            max_overflow=10,
            pool_timeout=30,
        )
        _session_factory = async_sessionmaker(
            bind=_engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the async session factory (creates the engine on first call)."""
    if _session_factory is None:
        get_engine()
    assert _session_factory is not None
    return _session_factory


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a scoped async session.

    Usage in a route::

        @router.get("/things")
        async def list_things(db: AsyncSession = Depends(get_db)):
            ...

    The session is closed automatically at the end of the request.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        # We do NOT auto-commit here — handlers that write should commit
        # explicitly. Read-only handlers don't need a commit.


async def dispose_engine() -> None:
    """Dispose the engine pool. Called on app shutdown and between tests."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
