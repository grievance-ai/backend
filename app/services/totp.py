"""TOTP two-factor auth with a Redis-backed replay guard.

A code that verifies once is recorded briefly in Redis so it cannot be reused
within its validity window (the classic TOTP replay defense).
"""

import base64
import io

import pyotp
import qrcode
import redis.asyncio as redis

from app.core.config import settings

_REPLAY_TTL = 90  # seconds (~3 time steps)


def generate_secret() -> str:
    return pyotp.random_base32()


def verify_totp(secret: str, code: str) -> bool:
    """Verify a code without the replay guard (for already-authenticated mutations)."""
    return bool(pyotp.TOTP(secret).verify(code, valid_window=1))


def provisioning_uri(secret: str, account_name: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=account_name, issuer_name=settings.totp_issuer)


def qr_code_data_uri(provisioning_uri: str) -> str:
    image = qrcode.make(provisioning_uri)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode()
    return f"data:image/png;base64,{encoded}"


class TOTPService:
    def __init__(self, redis_client: redis.Redis) -> None:
        self._redis = redis_client

    async def verify(self, user_id: str, secret: str, code: str) -> bool:
        if not pyotp.TOTP(secret).verify(code, valid_window=1):
            return False
        replay_key = f"otp_used:{user_id}:{code}"
        if await self._redis.get(replay_key) is not None:
            return False
        await self._redis.setex(replay_key, _REPLAY_TTL, "1")
        return True
