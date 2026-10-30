"""The citizen's grievances: review the assistant's draft, submit, and track."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import authorized_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import Envelope
from app.schemas.grievance import (
    CategoryOut,
    GrievanceDraftOut,
    GrievanceIn,
    GrievanceOut,
    GrievanceSummaryOut,
)
from app.services import grievance_service as service

router = APIRouter()


@router.get("/grievance-categories", response_model=Envelope[list[CategoryOut]])
async def list_categories(
    _user: User = Depends(authorized_user), db: AsyncSession = Depends(get_db)
) -> Envelope[list[CategoryOut]]:
    return Envelope[list[CategoryOut]](data=await service.list_categories(db))


@router.get("/grievances/draft", response_model=Envelope[GrievanceDraftOut])
async def get_draft(
    conversation_id: uuid.UUID | None = None,
    user: User = Depends(authorized_user),
    db: AsyncSession = Depends(get_db),
) -> Envelope[GrievanceDraftOut]:
    """The details the assistant collected in ``conversation_id``, ready to review."""
    return Envelope[GrievanceDraftOut](data=await service.get_draft(db, user, conversation_id))


@router.post("/grievances", response_model=Envelope[GrievanceOut], status_code=201)
async def submit_grievance(
    payload: GrievanceIn,
    user: User = Depends(authorized_user),
    db: AsyncSession = Depends(get_db),
) -> Envelope[GrievanceOut]:
    return Envelope[GrievanceOut](data=await service.submit(db, user, payload))


@router.get("/grievances", response_model=Envelope[list[GrievanceSummaryOut]])
async def list_my_grievances(
    user: User = Depends(authorized_user), db: AsyncSession = Depends(get_db)
) -> Envelope[list[GrievanceSummaryOut]]:
    return Envelope[list[GrievanceSummaryOut]](data=await service.list_mine(db, user))


@router.get("/grievances/{reference_no}", response_model=Envelope[GrievanceOut])
async def get_my_grievance(
    reference_no: str,
    user: User = Depends(authorized_user),
    db: AsyncSession = Depends(get_db),
) -> Envelope[GrievanceOut]:
    return Envelope[GrievanceOut](data=await service.get_mine(db, user, reference_no))
