"""API key management. Mutations are gated behind the user's TOTP (2FA)."""

import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.models.api_key import APIKey
from app.models.enums import DEFAULT_API_KEY_ALGORITHM, APIKeyState
from app.models.user import User
from app.services import totp

_HOLDER_TYPE = "User"


def _require_2fa(user: User, code: str) -> None:
    if not user.otp or not user.otp_secret:
        raise APIError(["resource.api_key.otp_required"], 403)
    if not totp.verify_totp(user.otp_secret, code):
        raise APIError(["resource.api_key.invalid_otp"], 403)


async def list_keys(db: AsyncSession, user_id: uuid.UUID) -> list[APIKey]:
    rows = await db.scalars(
        select(APIKey).where(
            APIKey.key_holder_account_id == user_id,
            APIKey.key_holder_account_type == _HOLDER_TYPE,
        )
    )
    return list(rows.all())


async def create_key(
    db: AsyncSession, user: User, *, otp_code: str, scope: list[str] | None
) -> tuple[APIKey, str]:
    _require_2fa(user, otp_code)
    secret = secrets.token_urlsafe(32)
    api_key = APIKey(
        kid=secrets.token_hex(16),
        secret=secret,
        algorithm=DEFAULT_API_KEY_ALGORITHM,
        scope=scope,
        state=APIKeyState.active.value,
        key_holder_account_id=user.id,
        key_holder_account_type=_HOLDER_TYPE,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)
    return api_key, secret


async def delete_key(db: AsyncSession, user: User, *, kid: str, otp_code: str) -> None:
    _require_2fa(user, otp_code)
    api_key = await db.scalar(
        select(APIKey).where(
            APIKey.kid == kid,
            APIKey.key_holder_account_id == user.id,
            APIKey.key_holder_account_type == _HOLDER_TYPE,
        )
    )
    if api_key is None:
        raise APIError(["resource.api_key.not_found"], 404)
    await db.delete(api_key)
    await db.commit()
