"""The user's API keys (HMAC credentials). Mutations are 2FA-gated."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import authorized_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import Envelope, Message
from app.schemas.resource import ApiKeyCreatedOut, ApiKeyCreateIn, ApiKeyDeleteIn, ApiKeyOut
from app.services import api_key_service

router = APIRouter()


@router.get("/api_keys", response_model=Envelope[list[ApiKeyOut]])
async def list_my_api_keys(
    user: User = Depends(authorized_user), db: AsyncSession = Depends(get_db)
) -> Envelope[list[ApiKeyOut]]:
    rows = await api_key_service.list_keys(db, user.id)
    return Envelope[list[ApiKeyOut]](data=[ApiKeyOut.model_validate(r) for r in rows])


@router.post(
    "/api_keys", response_model=Envelope[ApiKeyCreatedOut], status_code=status.HTTP_201_CREATED
)
async def create_api_key(
    payload: ApiKeyCreateIn,
    user: User = Depends(authorized_user),
    db: AsyncSession = Depends(get_db),
) -> Envelope[ApiKeyCreatedOut]:
    api_key, secret = await api_key_service.create_key(
        db, user, otp_code=payload.otp_code, scope=payload.scope
    )
    return Envelope[ApiKeyCreatedOut](
        data=ApiKeyCreatedOut(
            kid=api_key.kid,
            secret=secret,
            scope=api_key.scope,
            algorithm=api_key.algorithm,
            state=api_key.state,
        )
    )


@router.delete("/api_keys/{kid}", response_model=Envelope[Message])
async def delete_api_key(
    kid: str,
    payload: ApiKeyDeleteIn,
    user: User = Depends(authorized_user),
    db: AsyncSession = Depends(get_db),
) -> Envelope[Message]:
    await api_key_service.delete_key(db, user, kid=kid, otp_code=payload.otp_code)
    return Envelope[Message](data=Message(message="API key revoked."))
