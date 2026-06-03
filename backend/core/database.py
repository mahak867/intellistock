"""
IntelliStock — Async Database Layer
─────────────────────────────────────
SQLAlchemy 2.0 async engine with:
  • Connection pooling (size, overflow, timeout configured)
  • Automatic retry on transient errors
  • Alembic migration support
  • Dependency injection pattern for FastAPI
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from loguru import logger
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from tenacity import retry, stop_after_attempt, wait_fixed

from backend.core.config import settings
from backend.models.db_models import Base

# ─── Engine ─────────────────────────────────────────────────────────────────────

engine: AsyncEngine | None = None
AsyncSessionFactory: async_sessionmaker | None = None


def _create_engine() -> AsyncEngine:
    return create_async_engine(
        str(settings.DATABASE_URL),
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_pre_ping=True,  # detect stale connections before using them
        pool_recycle=3600,  # recycle connections after 1 hour
        echo=settings.is_development,
        future=True,
    )


# ─── Init ───────────────────────────────────────────────────────────────────────


@retry(stop=stop_after_attempt(5), wait=wait_fixed(3), reraise=True)
async def init_db() -> None:
    """Create engine, run migrations (dev) or verify schema (prod)."""
    global engine, AsyncSessionFactory

    engine = _create_engine()
    AsyncSessionFactory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    if settings.is_development:
        # Auto-create tables in dev — use Alembic in staging/prod
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables created (dev mode)")
    else:
        # In production: verify connection only, Alembic handles schema
        async with engine.connect() as conn:
            await conn.execute("SELECT 1")
        logger.info("Database connection verified")

    logger.info(
        f"Database ready: {settings.DATABASE_URL.host}:{settings.DATABASE_URL.port}"
    )


# ─── Session dependency ─────────────────────────────────────────────────────────


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Context manager that yields a transactional session."""
    if AsyncSessionFactory is None:
        raise RuntimeError("Database not initialised — call init_db() first")

    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that provides a database session."""
    async with get_session() as session:
        yield session


# ─── Teardown ───────────────────────────────────────────────────────────────────


async def close_db() -> None:
    global engine
    if engine:
        await engine.dispose()
        logger.info("Database connections closed")
