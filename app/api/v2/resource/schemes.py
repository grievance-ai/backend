"""The scheme catalogue citizens browse. Read-only; any logged-in user."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import authorized_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import Envelope
from app.schemas.scheme_catalog import SchemeInfoOut, SchemeSummaryOut
from app.services import scheme_catalog_service as service

router = APIRouter(prefix="/schemes")


@router.get("", response_model=Envelope[list[SchemeSummaryOut]])
async def list_schemes(
    user: User = Depends(authorized_user), db: AsyncSession = Depends(get_db)
) -> Envelope[list[SchemeSummaryOut]]:
    """Active central schemes and Punjab's own, by name."""
    return Envelope[list[SchemeSummaryOut]](data=await service.list_schemes(db))


@router.get("/{slug}", response_model=Envelope[SchemeInfoOut])
async def get_scheme(
    slug: str, user: User = Depends(authorized_user), db: AsyncSession = Depends(get_db)
) -> Envelope[SchemeInfoOut]:
    return Envelope[SchemeInfoOut](data=await service.get_scheme(db, slug))
