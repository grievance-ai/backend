"""Admin permission management (superadmin only). Edits bust the role cache."""

import uuid

import redis.asyncio as redis
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_redis, superadmin_authorized
from app.db.session import get_db
from app.models.user import User
from app.schemas.admin import PermissionCreateIn, PermissionOut, PermissionUpdateIn
from app.schemas.common import Envelope, Message, Page
from app.services import admin_service

router = APIRouter()


@router.get("/permissions", response_model=Envelope[Page[PermissionOut]])
async def list_permissions(
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
    _admin: User = Depends(superadmin_authorized),
    db: AsyncSession = Depends(get_db),
) -> Envelope[Page[PermissionOut]]:
    rows, total = await admin_service.list_permissions(db, page=page, limit=limit)
    return Envelope[Page[PermissionOut]](
        data=Page(
            items=[PermissionOut.model_validate(p) for p in rows],
            total=total,
            page=page,
            limit=limit,
        )
    )


@router.post("/permissions", response_model=Envelope[PermissionOut])
async def create_permission(
    payload: PermissionCreateIn,
    _admin: User = Depends(superadmin_authorized),
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
) -> Envelope[PermissionOut]:
    permission = await admin_service.create_permission(db, redis_client, payload)
    return Envelope[PermissionOut](data=PermissionOut.model_validate(permission))


@router.put("/permissions/{permission_id}", response_model=Envelope[PermissionOut])
async def update_permission(
    permission_id: uuid.UUID,
    payload: PermissionUpdateIn,
    _admin: User = Depends(superadmin_authorized),
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
) -> Envelope[PermissionOut]:
    permission = await admin_service.update_permission(db, redis_client, permission_id, payload)
    return Envelope[PermissionOut](data=PermissionOut.model_validate(permission))


@router.delete("/permissions/{permission_id}", response_model=Envelope[Message])
async def delete_permission(
    permission_id: uuid.UUID,
    _admin: User = Depends(superadmin_authorized),
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
) -> Envelope[Message]:
    await admin_service.delete_permission(db, redis_client, permission_id)
    return Envelope[Message](data=Message(message="Permission deleted."))
