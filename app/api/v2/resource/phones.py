"""The user's phone numbers (SMS delivery: Phase 10)."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import authorized_user
from app.core.config import settings
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import Envelope
from app.schemas.resource import PhoneCreatedOut, PhoneIn, PhoneOut, PhoneVerifyIn
from app.services import phone_service

router = APIRouter()


@router.get("/phones/me", response_model=Envelope[list[PhoneOut]])
async def list_my_phones(
    user: User = Depends(authorized_user), db: AsyncSession = Depends(get_db)
) -> Envelope[list[PhoneOut]]:
    rows = await phone_service.list_phones(db, user.id)
    return Envelope[list[PhoneOut]](data=[PhoneOut.model_validate(r) for r in rows])


@router.post(
    "/phones", response_model=Envelope[PhoneCreatedOut], status_code=status.HTTP_201_CREATED
)
async def add_phone(
    payload: PhoneIn,
    user: User = Depends(authorized_user),
    db: AsyncSession = Depends(get_db),
) -> Envelope[PhoneCreatedOut]:
    phone, code = await phone_service.create_phone(
        db, user, country=payload.country, number=payload.number
    )
    return Envelope[PhoneCreatedOut](
        data=PhoneCreatedOut(
            phone=PhoneOut.model_validate(phone),
            verification_code=None if settings.is_production else code,
        )
    )


@router.post("/phones/verify", response_model=Envelope[PhoneOut])
async def verify_phone(
    payload: PhoneVerifyIn,
    user: User = Depends(authorized_user),
    db: AsyncSession = Depends(get_db),
) -> Envelope[PhoneOut]:
    phone = await phone_service.verify_phone(db, user, phone_id=payload.phone_id, code=payload.code)
    return Envelope[PhoneOut](data=PhoneOut.model_validate(phone))
