"""The citizen's own profile and the district list used to fill it in."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import authorized_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.citizen import CitizenProfileOut, CitizenProfileUpdate, DistrictOut
from app.schemas.common import Envelope
from app.services import citizen_profile_service as service

router = APIRouter()


@router.get("/citizen-profile/me", response_model=Envelope[CitizenProfileOut])
async def get_my_profile(
    user: User = Depends(authorized_user), db: AsyncSession = Depends(get_db)
) -> Envelope[CitizenProfileOut]:
    profile = await service.get_or_create(db, user)
    return Envelope[CitizenProfileOut](data=service.to_out(user, profile))


@router.patch("/citizen-profile", response_model=Envelope[CitizenProfileOut])
async def update_my_profile(
    payload: CitizenProfileUpdate,
    user: User = Depends(authorized_user),
    db: AsyncSession = Depends(get_db),
) -> Envelope[CitizenProfileOut]:
    """Update any subset of name, age, gender, marital status, district, area
    and preferred language."""
    return Envelope[CitizenProfileOut](data=await service.update(db, user, payload))


@router.get("/districts", response_model=Envelope[list[DistrictOut]])
async def list_districts(
    _user: User = Depends(authorized_user), db: AsyncSession = Depends(get_db)
) -> Envelope[list[DistrictOut]]:
    return Envelope[list[DistrictOut]](data=await service.list_districts(db))
