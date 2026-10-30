"""Async Redis client (sessions, token state, cache, rate-limit counters)."""

import redis.asyncio as redis

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

redis_client: redis.Redis = redis.from_url(  # type: ignore[no-untyped-call]
    settings.redis_url,
    encoding="utf-8",
    decode_responses=True,
)


async def check_redis() -> bool:
    """Return ``True`` if Redis responds to PING."""
    try:
        return bool(await redis_client.ping())
    except Exception:
        logger.warning("redis_unreachable", exc_info=True)
        return False
