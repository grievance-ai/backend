"""JWT access/refresh lifecycle backed by Redis.

Each refresh token's ``jti`` is tracked in Redis so sessions can be rotated on
refresh and revoked individually (logout) or all at once (password change,
2FA toggle, ban). Also sets/clears the httpOnly auth cookies.
"""

from dataclasses import dataclass

import jwt
import redis.asyncio as redis
from fastapi import Response

from app.core import security
from app.core.config import settings
from app.core.csrf import generate_csrf_token
from app.core.errors import APIError


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    csrf_token: str


def _refresh_key(jti: str) -> str:
    return f"refresh:{jti}"


def _user_set_key(user_id: str) -> str:
    return f"user:{user_id}:refresh"


class TokenService:
    def __init__(self, redis_client: redis.Redis) -> None:
        self._redis = redis_client

    async def issue_pair(self, *, user_id: str, role: str) -> TokenPair:
        access_token, _ = security.create_access_token(user_id, role)
        refresh_token, jti = security.create_refresh_token(user_id, role)
        await self._register_refresh(user_id, jti)
        return TokenPair(access_token, refresh_token, generate_csrf_token())

    async def rotate(self, refresh_token: str) -> TokenPair:
        try:
            payload = security.decode_token(refresh_token, expected_type=security.REFRESH_TYPE)
        except jwt.InvalidTokenError as exc:
            raise APIError(["identity.session.invalid_token"], 401) from exc

        jti = payload["jti"]
        user_id = payload["uid"]
        if await self._redis.get(_refresh_key(jti)) is None:
            raise APIError(["identity.session.invalid_token"], 401)

        await self.revoke(jti, user_id)
        return await self.issue_pair(user_id=user_id, role=payload.get("role", ""))

    async def revoke(self, jti: str, user_id: str | None = None) -> None:
        await self._redis.delete(_refresh_key(jti))
        if user_id is not None:
            # redis-py stubs set commands as Awaitable[int] | int; the async client awaits fine.
            await self._redis.srem(_user_set_key(user_id), jti)  # type: ignore[misc]

    async def invalidate_all(self, user_id: str) -> None:
        set_key = _user_set_key(user_id)
        for jti in await self._redis.smembers(set_key):  # type: ignore[misc]
            await self._redis.delete(_refresh_key(jti))
        await self._redis.delete(set_key)

    async def _register_refresh(self, user_id: str, jti: str) -> None:
        await self._redis.setex(_refresh_key(jti), settings.refresh_token_ttl, user_id)
        await self._redis.sadd(_user_set_key(user_id), jti)  # type: ignore[misc]
        await self._redis.expire(_user_set_key(user_id), settings.refresh_token_ttl)


# --- cookie helpers ----------------------------------------------------------
def set_auth_cookies(response: Response, pair: TokenPair) -> None:
    response.set_cookie(
        settings.access_cookie_name,
        pair.access_token,
        max_age=settings.access_token_ttl,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        domain=settings.cookie_domain,
        path="/",
    )
    response.set_cookie(
        settings.refresh_cookie_name,
        pair.refresh_token,
        max_age=settings.refresh_token_ttl,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        domain=settings.cookie_domain,
        path="/",
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        pair.csrf_token,
        max_age=settings.refresh_token_ttl,
        httponly=False,  # readable by the frontend for the double-submit header
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        domain=settings.cookie_domain,
        path="/",
    )


def clear_auth_cookies(response: Response) -> None:
    for name in (
        settings.access_cookie_name,
        settings.refresh_cookie_name,
        settings.csrf_cookie_name,
    ):
        response.delete_cookie(name, domain=settings.cookie_domain, path="/")
