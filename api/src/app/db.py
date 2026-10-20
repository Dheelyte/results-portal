"""Database engine, session factory and the readiness probe.

The engine is built at import time rather than in the application lifespan, so
tests can drive the ASGI app with no lifespan manager.
"""

from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(
    settings.dsn,
    # Verifies a pooled connection before handing it out.  Postgres restarts and
    # idle-connection reaping are otherwise seen as a failed first request.
    pool_pre_ping=True,
    echo=False,
    future=True,
)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a session that is always closed."""
    async with SessionLocal() as session:
        yield session


async def check_database() -> bool:
    """True when the database answers a trivial query.

    Raises nothing: the caller gets a boolean, so no driver message or DSN can
    reach a response body through an unhandled exception.
    """
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        return False
    return True
