"""Officer and administrator endpoints (spec §5.9, §5.10).

Role and jurisdiction are enforced in ``staff_service`` on every call; citizens get 403.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import authorized_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import Envelope
from app.schemas.grievance import NamedOut
from app.schemas.scheme_admin import SchemeDetailOut, SchemeListOut, SchemeReviewIn
from app.schemas.staff import (
    NoteIn,
    OverviewOut,
    StaffGrievanceList,
    StaffGrievanceOut,
    StaffMeOut,
    StatusChangeIn,
)
from app.services import scheme_admin_service
from app.services import staff_service as service

router = APIRouter(prefix="/staff")


@router.get("/me", response_model=Envelope[StaffMeOut])
async def staff_me(
    user: User = Depends(authorized_user), db: AsyncSession = Depends(get_db)
) -> Envelope[StaffMeOut]:
    return Envelope[StaffMeOut](data=await service.me(db, user))


@router.get("/grievances", response_model=Envelope[StaffGrievanceList])
async def list_queue(
    status: str | None = Query(default=None, max_length=25),
    district: str | None = Query(default=None, max_length=10),
    department: str | None = Query(default=None, max_length=30),
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(authorized_user),
    db: AsyncSession = Depends(get_db),
) -> Envelope[StaffGrievanceList]:
    """The grievance queue for the caller's jurisdiction. ``status`` also takes
    ``open`` (every unfinished status) and ``overdue``."""
    data = await service.list_queue(
        db,
        user,
        status=status,
        district_code=district,
        department_code=department,
        query=q,
        limit=limit,
        offset=offset,
    )
    return Envelope[StaffGrievanceList](data=data)


@router.get("/departments", response_model=Envelope[list[NamedOut]])
async def departments(
    user: User = Depends(authorized_user), db: AsyncSession = Depends(get_db)
) -> Envelope[list[NamedOut]]:
    """Departments for the queue's filter (only the caller's own, if they have one)."""
    return Envelope[list[NamedOut]](data=await service.departments(db, user))


@router.get("/grievances/{reference_no}", response_model=Envelope[StaffGrievanceOut])
async def get_grievance(
    reference_no: str, user: User = Depends(authorized_user), db: AsyncSession = Depends(get_db)
) -> Envelope[StaffGrievanceOut]:
    return Envelope[StaffGrievanceOut](data=await service.get_grievance(db, user, reference_no))


@router.post("/grievances/{reference_no}/status", response_model=Envelope[StaffGrievanceOut])
async def change_status(
    reference_no: str,
    payload: StatusChangeIn,
    user: User = Depends(authorized_user),
    db: AsyncSession = Depends(get_db),
) -> Envelope[StaffGrievanceOut]:
    data = await service.change_status(db, user, reference_no, payload)
    return Envelope[StaffGrievanceOut](data=data)


@router.post("/grievances/{reference_no}/notes", response_model=Envelope[StaffGrievanceOut])
async def add_note(
    reference_no: str,
    payload: NoteIn,
    user: User = Depends(authorized_user),
    db: AsyncSession = Depends(get_db),
) -> Envelope[StaffGrievanceOut]:
    return Envelope[StaffGrievanceOut](data=await service.add_note(db, user, reference_no, payload))


@router.get("/overview", response_model=Envelope[OverviewOut])
async def overview(
    days: int = Query(default=30, ge=1, le=365),
    district: str | None = Query(default=None, max_length=10),
    department: str | None = Query(default=None, max_length=30),
    user: User = Depends(authorized_user),
    db: AsyncSession = Depends(get_db),
) -> Envelope[OverviewOut]:
    """Administrator dashboard numbers for the caller's jurisdiction, optionally
    narrowed to one district and/or department within it."""
    data = await service.overview(
        db, user, days=days, district_code=district, department_code=department
    )
    return Envelope[OverviewOut](data=data)


# --- scheme knowledge base (administrators) -------------------------------------------


@router.get("/schemes", response_model=Envelope[SchemeListOut])
async def list_schemes(
    user: User = Depends(authorized_user), db: AsyncSession = Depends(get_db)
) -> Envelope[SchemeListOut]:
    """Every scheme with its source and review status, plus open unanswered questions."""
    return Envelope[SchemeListOut](data=await scheme_admin_service.list_schemes(db, user))


@router.get("/schemes/{slug}", response_model=Envelope[SchemeDetailOut])
async def get_scheme(
    slug: str, user: User = Depends(authorized_user), db: AsyncSession = Depends(get_db)
) -> Envelope[SchemeDetailOut]:
    return Envelope[SchemeDetailOut](data=await scheme_admin_service.get_scheme(db, user, slug))


@router.post("/schemes/{slug}/review", response_model=Envelope[SchemeDetailOut])
async def review_scheme(
    slug: str,
    payload: SchemeReviewIn,
    user: User = Depends(authorized_user),
    db: AsyncSession = Depends(get_db),
) -> Envelope[SchemeDetailOut]:
    """Mark a scheme as checked against its source, or back to needs review.
    State or system administrators only."""
    data = await scheme_admin_service.set_review(db, user, slug, payload)
    return Envelope[SchemeDetailOut](data=data)
