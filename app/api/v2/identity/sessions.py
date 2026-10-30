"""Login, token refresh, and logout."""

import jwt
import redis.asyncio as redis
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import client_ip, get_redis
from app.core import security
from app.core import tokens as token_cookies
from app.core.activity import log_activity, request_meta
from app.core.config import settings
from app.core.errors import APIError
from app.core.ratelimit import limiter
from app.core.tokens import TokenService
from app.db.session import get_db
from app.schemas.common import Envelope, Message
from app.schemas.identity import (
    CsrfOut,
    LoginIn,
    MobileLoginIn,
    MobileSessionOut,
    SessionOut,
    UserOut,
)
from app.services import auth_service, citizen_profile_service

router = APIRouter()


@router.post("/sessions", response_model=Envelope[SessionOut])
@limiter.limit(settings.rate_limit_login)
async def create_session(
    payload: LoginIn,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
) -> Envelope[SessionOut]:
    user, pair = await auth_service.login(
        db,
        redis_client,
        email=payload.email,
        password=payload.password,
        otp_code=payload.otp_code,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
        captcha_response=payload.captcha_response,
    )
    token_cookies.set_auth_cookies(response, pair)
    return Envelope[SessionOut](
        data=SessionOut(user=UserOut.model_validate(user), csrf_token=pair.csrf_token)
    )


@router.post("/sessions/mobile", response_model=Envelope[MobileSessionOut])
@limiter.limit(settings.rate_limit_login)
async def create_mobile_session(
    payload: MobileLoginIn,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
) -> Envelope[MobileSessionOut]:
    """Prototype citizen login: mobile + fixed OTP (creates the citizen on first use)."""
    user, pair = await auth_service.mobile_login(
        db,
        redis_client,
        mobile=payload.mobile,
        otp=payload.otp,
        language=payload.language,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    token_cookies.set_auth_cookies(response, pair)
    profile = await citizen_profile_service.get_or_create(db, user)
    return Envelope[MobileSessionOut](
        data=MobileSessionOut(
            user=UserOut.model_validate(user),
            csrf_token=pair.csrf_token,
            profile_complete=citizen_profile_service.is_complete(user, profile),
        )
    )


@router.post("/sessions/refresh", response_model=Envelope[CsrfOut])
async def refresh_session(
    request: Request,
    response: Response,
    redis_client: redis.Redis = Depends(get_redis),
) -> Envelope[CsrfOut]:
    refresh_token = request.cookies.get(settings.refresh_cookie_name)
    if not refresh_token:
        raise APIError(["identity.session.invalid_token"], 401)
    pair = await TokenService(redis_client).rotate(refresh_token)
    token_cookies.set_auth_cookies(response, pair)
    return Envelope[CsrfOut](data=CsrfOut(csrf_token=pair.csrf_token))


@router.delete("/sessions", response_model=Envelope[Message])
async def delete_session(
    request: Request,
    response: Response,
    redis_client: redis.Redis = Depends(get_redis),
) -> Envelope[Message]:
    refresh_token = request.cookies.get(settings.refresh_cookie_name)
    if refresh_token:
        try:
            payload = security.decode_token(refresh_token, expected_type=security.REFRESH_TYPE)
            await TokenService(redis_client).revoke(payload["jti"], payload["uid"])
            ip, user_agent = request_meta(request)
            log_activity(
                topic="session",
                action="logout",
                result="succeed",
                category="identity",
                user_id=payload["uid"],
                ip=ip,
                user_agent=user_agent,
            )
        except jwt.InvalidTokenError:
            pass  # already invalid; just clear the cookies
    token_cookies.clear_auth_cookies(response)
    return Envelope[Message](data=Message(message="signed out"))
