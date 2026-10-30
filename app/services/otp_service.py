"""Two-factor (TOTP) setup, enable, and disable for a user."""

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.core.tokens import TokenService
from app.models.user import User
from app.services import totp


async def generate(db: AsyncSession, user: User) -> tuple[str, str, str]:
    if user.otp:
        raise APIError(["resource.otp.already_enabled"], 409)
    secret = totp.generate_secret()
    user.otp_secret = secret
    await db.commit()
    uri = totp.provisioning_uri(secret, user.email or user.mobile or user.uid)
    return secret, uri, totp.qr_code_data_uri(uri)


async def enable(db: AsyncSession, redis_client: redis.Redis, user: User, *, code: str) -> None:
    if user.otp:
        raise APIError(["resource.otp.already_enabled"], 409)
    if not user.otp_secret:
        raise APIError(["resource.otp.not_generated"], 422)
    if not totp.verify_totp(user.otp_secret, code):
        raise APIError(["resource.otp.invalid_code"], 422)
    user.otp = True
    await db.commit()
    await TokenService(redis_client).invalidate_all(str(user.id))  # force re-login with 2FA


async def disable(db: AsyncSession, user: User, *, code: str) -> None:
    if not user.otp or not user.otp_secret:
        raise APIError(["resource.otp.not_enabled"], 422)
    if not totp.verify_totp(user.otp_secret, code):
        raise APIError(["resource.otp.invalid_code"], 422)
    user.otp = False
    user.otp_secret = None
    await db.commit()
