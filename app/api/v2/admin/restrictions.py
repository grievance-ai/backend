"""Admin restriction management (superadmin only). Edits bust the 5-minute
restriction cache so they take effect promptly."""

import uuid

import redis.asyncio as redis
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_redis, superadmin_authorized
from app.db.session import get_db
from app.models.user import User
from app.schemas.admin import RestrictionCreateIn, RestrictionOut, RestrictionUpdateIn
from app.schemas.common import Envelope, Message, Page
from app.services import admin_service

router = APIRouter()


@router.get("/restrictions", response_model=Envelope[Page[RestrictionOut]])
async def list_restrictions(
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
    _admin: User = Depends(superadmin_authorized),
    db: AsyncSession = Depends(get_db),
) -> Envelope[Page[RestrictionOut]]:
    rows, total = await admin_service.list_restrictions(db, page=page, limit=limit)
    return Envelope[Page[RestrictionOut]](
        data=Page(
            items=[RestrictionOut.model_validate(r) for r in rows],
            total=total,
            page=page,
            limit=limit,
        )
    )


@router.post("/restrictions", response_model=Envelope[RestrictionOut])
async def create_restriction(
    payload: RestrictionCreateIn,
    _admin: User = Depends(superadmin_authorized),
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
) -> Envelope[RestrictionOut]:
    restriction = await admin_service.create_restriction(db, redis_client, payload)
    return Envelope[RestrictionOut](data=RestrictionOut.model_validate(restriction))


@router.put("/restrictions/{restriction_id}", response_model=Envelope[RestrictionOut])
async def update_restriction(
    restriction_id: uuid.UUID,
    payload: RestrictionUpdateIn,
    _admin: User = Depends(superadmin_authorized),
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
) -> Envelope[RestrictionOut]:
    restriction = await admin_service.update_restriction(db, redis_client, restriction_id, payload)
    return Envelope[RestrictionOut](data=RestrictionOut.model_validate(restriction))


@router.delete("/restrictions/{restriction_id}", response_model=Envelope[Message])
async def delete_restriction(
    restriction_id: uuid.UUID,
    _admin: User = Depends(superadmin_authorized),
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
) -> Envelope[Message]:
    await admin_service.delete_restriction(db, redis_client, restriction_id)
    return Envelope[Message](data=Message(message="Restriction deleted."))
