"""User registration."""

import redis.asyncio as redis
from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_redis
from app.core import tokens as token_cookies
from app.core.activity import log_activity, request_meta
from app.core.tokens import TokenService
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.identity import RegisterIn, SessionOut, UserOut
from app.services import auth_service

router = APIRouter()


@router.post("/users", response_model=Envelope[SessionOut], status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: RegisterIn,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
) -> Envelope[SessionOut]:
    user = await auth_service.register(
        db,
        email=payload.email,
        password=payload.password,
        username=payload.username,
        captcha_response=payload.captcha_response,
    )
    ip, user_agent = request_meta(request)
    log_activity(
        topic="user",
        action="register",
        result="succeed",
        category="identity",
        user_id=user.id,
        ip=ip,
        user_agent=user_agent,
    )
    # Email confirmation is sent via /email/generate_code (delivery worker: Phase 9).
    pair = await TokenService(redis_client).issue_pair(user_id=str(user.id), role=user.role)
    token_cookies.set_auth_cookies(response, pair)
    return Envelope[SessionOut](
        data=SessionOut(user=UserOut.model_validate(user), csrf_token=pair.csrf_token)
    )
