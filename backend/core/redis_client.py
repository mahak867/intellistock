"""
IntelliStock — Redis Client
────────────────────────────
Async Redis connection pool used for:
  • JWT token revocation list
  • Refresh token store
  • Prediction result cache (15 min TTL)
  • Rate limit counters (via slowapi)
  • Celery broker + result backend
"""

from __future__ import annotations

import redis.asyncio as aioredis
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_fixed

from backend.core.config import settings

_redis_pool: aioredis.Redis | None = None


@retry(stop=stop_after_attempt(5), wait=wait_fixed(2), reraise=True)
async def init_redis() -> None:
    global _redis_pool
    _redis_pool = aioredis.from_url(
        str(settings.REDIS_URL),
        encoding="utf-8",
        decode_responses=True,
        max_connections=50,
        socket_connect_timeout=5,
        socket_timeout=5,
        retry_on_timeout=True,
        health_check_interval=30,
    )
    # Verify connection
    await _redis_pool.ping()
    logger.info("Redis connected")


async def get_redis_client() -> aioredis.Redis:
    if _redis_pool is None:
        raise RuntimeError("Redis not initialised — call init_redis() first")
    return _redis_pool


async def close_redis() -> None:
    global _redis_pool
    if _redis_pool:
        await _redis_pool.aclose()
        logger.info("Redis connection closed")
