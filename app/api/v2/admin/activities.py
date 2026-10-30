"""Admin audit-log viewer: filter the immutable activity trail."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import authorized_user
from app.db.session import get_db
from app.models.activity import Activity
from app.models.user import User
from app.queries.activity_filter import ActivityFilter
from app.schemas.admin import ActivityOut
from app.schemas.common import Envelope, Page
from app.services import admin_service

router = APIRouter()


def _ts(value: int | None) -> datetime | None:
    return datetime.fromtimestamp(value, tz=UTC) if value is not None else None


@router.get("/activities", response_model=Envelope[Page[ActivityOut]])
async def list_activities(
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
    action: str | None = None,
    topic: str | None = None,
    uid: str | None = None,
    email: str | None = None,
    date_from: int | None = Query(None, description="Unix seconds (inclusive lower bound)"),
    date_to: int | None = Query(None, description="Unix seconds (inclusive upper bound)"),
    _admin: User = Depends(authorized_user),
    db: AsyncSession = Depends(get_db),
) -> Envelope[Page[ActivityOut]]:
    f = ActivityFilter(
        action=action,
        topic=topic,
        uid=uid,
        email=email,
        date_from=_ts(date_from),
        date_to=_ts(date_to),
    )
    rows, total = await admin_service.list_activities(db, f, page=page, limit=limit)
    activities: list[Activity] = rows
    return Envelope[Page[ActivityOut]](
        data=Page(
            items=[ActivityOut.model_validate(a) for a in activities],
            total=total,
            page=page,
            limit=limit,
        )
    )
