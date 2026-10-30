"""The user's profile (encrypted PII)."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import authorized_user
from app.core.errors import APIError
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import Envelope
from app.schemas.resource import ProfileIn, ProfileOut
from app.services import profile_service

router = APIRouter()


@router.get("/profiles/me", response_model=Envelope[ProfileOut])
async def get_my_profile(
    user: User = Depends(authorized_user), db: AsyncSession = Depends(get_db)
) -> Envelope[ProfileOut]:
    profile = await profile_service.get_profile(db, user.id)
    if profile is None:
        raise APIError(["resource.profile.not_found"], 404)
    return Envelope[ProfileOut](data=ProfileOut.model_validate(profile))


@router.post("/profiles", response_model=Envelope[ProfileOut], status_code=status.HTTP_201_CREATED)
async def upsert_my_profile(
    payload: ProfileIn,
    user: User = Depends(authorized_user),
    db: AsyncSession = Depends(get_db),
) -> Envelope[ProfileOut]:
    profile = await profile_service.upsert_profile(db, user, **payload.model_dump())
    return Envelope[ProfileOut](data=ProfileOut.model_validate(profile))
