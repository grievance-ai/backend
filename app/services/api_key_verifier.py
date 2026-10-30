"""API-key HMAC verification with a nonce window and replay guard.

A client signs ``HMAC-SHA256(secret, nonce + kid)``. The request is accepted
only if the nonce (a millisecond timestamp) is within the allowed window, the
signature matches, and the nonce has not already been used in that window.
"""

import hashlib
import hmac
import time

import redis.asyncio as redis

from app.core.config import settings


def expected_signature(secret: str, nonce: str, kid: str) -> str:
    return hmac.new(secret.encode(), f"{nonce}{kid}".encode(), hashlib.sha256).hexdigest()


class APIKeyVerifier:
    def __init__(self, redis_client: redis.Redis) -> None:
        self._redis = redis_client

    async def verify(self, *, kid: str, nonce: str, signature: str, secret: str) -> bool:
        try:
            nonce_ms = int(nonce)
        except ValueError:
            return False

        now_ms = int(time.time() * 1000)
        if abs(now_ms - nonce_ms) > settings.api_key_nonce_window_ms:
            return False

        if not hmac.compare_digest(expected_signature(secret, nonce, kid), signature):
            return False

        replay_key = f"apikey_nonce:{kid}:{nonce}"
        if await self._redis.get(replay_key) is not None:
            return False
        await self._redis.setex(replay_key, settings.api_key_nonce_window_ms // 1000 + 1, "1")
        return True
