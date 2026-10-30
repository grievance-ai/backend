"""Shared FastAPI dependencies: authentication and authorization."""

import uuid

import jwt
import redis.asyncio as redis
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import HTTPConnection

from app.core import security
from app.core.activity import log_activity, request_meta
from app.core.authorize import authorize
from app.core.config import settings
from app.core.csrf import CSRF_HEADER, tokens_match
from app.core.errors import APIError
from app.core.redis import redis_client
from app.db.session import get_db
from app.models.api_key import APIKey
from app.models.enums import APIKeyState, UserState
from app.models.user import User
from app.services.api_key_verifier import APIKeyVerifier

ADMIN_ROLES = frozenset({"admin", "superadmin"})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# Non-authenticatable states (banned/locked/deleted); pending may still act.
_BLOCKED_STATES = frozenset(
    {UserState.banned.value, UserState.locked.value, UserState.deleted.value}
)


async def get_redis() -> redis.Redis:
    return redis_client


async def restriction_guard(
    request: HTTPConnection,  # also runs for WebSocket routes (live voice)
    db: AsyncSession = Depends(get_db),
    redis_dep: redis.Redis = Depends(get_redis),
) -> None:
    """Enforce IP/geo restrictions before any API handler runs."""
    from app.core import restrictions

    await restrictions.evaluate(request, redis_dep, db)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _access_token(request: Request) -> str | None:
    cookie = request.cookies.get(settings.access_cookie_name)
    if cookie:
        return cookie
    header = request.headers.get("authorization")
    if header and header.lower().startswith("bearer "):
        return header[len("bearer ") :]
    return None


async def current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    """Authenticate via the access cookie (or a Bearer header for tooling)."""
    return await user_from_access_token(_access_token(request), db)


async def user_from_access_token(token: str | None, db: AsyncSession) -> User:
    """The active user an access JWT belongs to; 401 otherwise. Shared with WebSockets."""
    if not token:
        raise APIError(["authz.unauthorized"], 401)
    try:
        payload = security.decode_token(token, expected_type=security.ACCESS_TYPE)
    except jwt.InvalidTokenError as exc:
        raise APIError(["authz.invalid_token"], 401) from exc
    user = await db.get(User, uuid.UUID(payload["uid"]))
    if user is None or user.state in _BLOCKED_STATES:
        raise APIError(["authz.invalid_session"], 401)
    return user


async def _api_key_user(request: Request, db: AsyncSession, redis_client: redis.Redis) -> User:
    kid = request.headers.get("x-auth-apikey")
    nonce = request.headers.get("x-auth-nonce")
    signature = request.headers.get("x-auth-signature")
    if not (kid and nonce and signature):
        raise APIError(["authz.apikey.invalid"], 401)
    api_key = await db.scalar(
        select(APIKey).where(APIKey.kid == kid, APIKey.state == APIKeyState.active.value)
    )
    if api_key is None or not await APIKeyVerifier(redis_client).verify(
        kid=kid, nonce=nonce, signature=signature, secret=api_key.secret
    ):
        raise APIError(["authz.apikey.invalid"], 401)
    if api_key.key_holder_account_type != "User":
        raise APIError(["authz.apikey.invalid"], 401)
    user = await db.get(User, api_key.key_holder_account_id)
    if user is None:
        raise APIError(["authz.apikey.invalid"], 401)
    return user


async def authorized_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
) -> User:
    """Authenticate (cookie or API key), enforce CSRF on writes, then authorize."""
    if request.headers.get("x-auth-apikey"):
        user = await _api_key_user(request, db, redis_client)
    else:
        user = await current_user(request, db)
        if request.method not in SAFE_METHODS and not tokens_match(
            request.cookies.get(settings.csrf_cookie_name), request.headers.get(CSRF_HEADER)
        ):
            raise APIError(["identity.csrf.invalid"], 403)
    topics = await authorize(
        db, redis_client, role=user.role, method=request.method, path=request.url.path
    )
    if topics:
        ip, user_agent = request_meta(request)
        for topic in topics:
            log_activity(
                topic=topic,
                action=request.method,
                result="succeed",
                category="audit",
                user_id=user.id,
                ip=ip,
                user_agent=user_agent,
                data={"path": request.url.path},
            )
    return user


async def admin_user(user: User = Depends(current_user)) -> User:
    if user.role not in ADMIN_ROLES:
        raise APIError(["authz.forbidden"], 403)
    return user


async def require_superadmin(user: User = Depends(current_user)) -> User:
    if user.role != "superadmin":
        raise APIError(["authz.forbidden"], 403)
    return user


async def superadmin_authorized(user: User = Depends(authorized_user)) -> User:
    """Full RBAC + CSRF authorization, then restrict to superadmin (e.g. for
    permission management)."""
    if user.role != "superadmin":
        raise APIError(["authz.forbidden"], 403)
    return user
