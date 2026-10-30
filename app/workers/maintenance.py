"""Periodic maintenance tasks run by Celery beat.

These are housekeeping sweeps, not request-path work. The schedule lives in
``app/workers/celery_app.py``.
"""

from redis import Redis

from app.core.config import settings
from app.core.logging import get_logger
from app.workers.celery_app import celery_app

logger = get_logger(__name__)


def _redis_client() -> Redis:
    """The synchronous Redis client used by beat tasks (patched in tests)."""
    return Redis.from_url(settings.redis_url, decode_responses=True)


@celery_app.task(name="maintenance.clean_expired_tokens")  # type: ignore[untyped-decorator]
def clean_expired_tokens() -> int:
    """Prune dangling refresh-token references whose token key has expired.

    A refresh token's ``refresh:{jti}`` key carries a TTL and disappears on its
    own, but the jti can linger in the per-user set (``user:{id}:refresh``) until
    that set itself expires. This daily sweep removes those orphaned references
    so the per-user sets stay accurate. Returns the number of references pruned.
    """
    client = _redis_client()
    removed = 0
    try:
        for set_key in client.scan_iter(match="user:*:refresh"):
            for jti in client.smembers(set_key):  # type: ignore[union-attr]
                if not client.exists(f"refresh:{jti}"):
                    client.srem(set_key, jti)
                    removed += 1
    finally:
        client.close()
    logger.info("clean_expired_tokens", pruned=removed)
    return removed
