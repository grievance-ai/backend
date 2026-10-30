"""Two-factor authentication setup for the user."""

import redis.asyncio as redis
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import authorized_user, get_redis
from app.core.activity import log_activity, request_meta
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import Envelope, Message
from app.schemas.resource import OtpCodeIn, OtpGenerateOut
from app.services import otp_service

router = APIRouter()


@router.post("/otp/generate_qrcode", response_model=Envelope[OtpGenerateOut])
async def generate_qrcode(
    user: User = Depends(authorized_user), db: AsyncSession = Depends(get_db)
) -> Envelope[OtpGenerateOut]:
    secret, uri, qr_code = await otp_service.generate(db, user)
    return Envelope[OtpGenerateOut](
        data=OtpGenerateOut(secret=secret, provisioning_uri=uri, qr_code=qr_code)
    )


@router.post("/otp/enable", response_model=Envelope[Message])
async def enable_otp(
    payload: OtpCodeIn,
    request: Request,
    user: User = Depends(authorized_user),
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
) -> Envelope[Message]:
    await otp_service.enable(db, redis_client, user, code=payload.code)
    ip, user_agent = request_meta(request)
    log_activity(
        topic="otp",
        action="enable",
        result="succeed",
        user_id=user.id,
        ip=ip,
        user_agent=user_agent,
    )
    return Envelope[Message](data=Message(message="Two-factor authentication enabled."))


@router.post("/otp/disable", response_model=Envelope[Message])
async def disable_otp(
    payload: OtpCodeIn,
    request: Request,
    user: User = Depends(authorized_user),
    db: AsyncSession = Depends(get_db),
) -> Envelope[Message]:
    await otp_service.disable(db, user, code=payload.code)
    ip, user_agent = request_meta(request)
    log_activity(
        topic="otp",
        action="disable",
        result="succeed",
        user_id=user.id,
        ip=ip,
        user_agent=user_agent,
    )
    return Envelope[Message](data=Message(message="Two-factor authentication disabled."))
