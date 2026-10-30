"""Admin user management: list/filter, inspect, and change state/role/otp/labels."""

import redis.asyncio as redis
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import authorized_user, get_redis
from app.db.session import get_db
from app.models.user import User
from app.queries.user_filter import UserFilter
from app.schemas.admin import AdminLabelIn, AdminUserOut, UserOtpIn, UserRoleIn, UserStateIn
from app.schemas.common import Envelope, Page
from app.schemas.identity import UserOut
from app.services import admin_service

router = APIRouter()


@router.get("/users", response_model=Envelope[Page[UserOut]])
async def list_users(
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
    uid: str | None = None,
    email: str | None = None,
    role: str | None = None,
    state: str | None = None,
    level: int | None = None,
    _admin: User = Depends(authorized_user),
    db: AsyncSession = Depends(get_db),
) -> Envelope[Page[UserOut]]:
    f = UserFilter(uid=uid, email=email, role=role, state=state, level=level)
    rows, total = await admin_service.list_users(db, f, page=page, limit=limit)
    return Envelope[Page[UserOut]](
        data=Page(
            items=[UserOut.model_validate(u) for u in rows], total=total, page=page, limit=limit
        )
    )


@router.get("/users/{uid}", response_model=Envelope[AdminUserOut])
async def get_user(
    uid: str,
    _admin: User = Depends(authorized_user),
    db: AsyncSession = Depends(get_db),
) -> Envelope[AdminUserOut]:
    user = await admin_service.get_user(db, uid)
    return Envelope[AdminUserOut](data=AdminUserOut.model_validate(user))


@router.put("/users/{uid}/state", response_model=Envelope[UserOut])
async def set_user_state(
    uid: str,
    payload: UserStateIn,
    _admin: User = Depends(authorized_user),
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
) -> Envelope[UserOut]:
    user = await admin_service.set_state(db, redis_client, uid=uid, state=payload.state)
    return Envelope[UserOut](data=UserOut.model_validate(user))


@router.put("/users/{uid}/role", response_model=Envelope[UserOut])
async def set_user_role(
    uid: str,
    payload: UserRoleIn,
    _admin: User = Depends(authorized_user),
    db: AsyncSession = Depends(get_db),
) -> Envelope[UserOut]:
    user = await admin_service.set_role(db, uid=uid, role=payload.role)
    return Envelope[UserOut](data=UserOut.model_validate(user))


@router.put("/users/{uid}/otp", response_model=Envelope[UserOut])
async def disable_user_otp(
    uid: str,
    payload: UserOtpIn,
    _admin: User = Depends(authorized_user),
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
) -> Envelope[UserOut]:
    user = await admin_service.disable_otp(db, redis_client, uid=uid, otp=payload.otp)
    return Envelope[UserOut](data=UserOut.model_validate(user))


@router.post("/users/{uid}/labels", response_model=Envelope[UserOut])
async def add_user_label(
    uid: str,
    payload: AdminLabelIn,
    _admin: User = Depends(authorized_user),
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
) -> Envelope[UserOut]:
    user = await admin_service.add_user_label(
        db, redis_client, uid=uid, key=payload.key, value=payload.value, scope=payload.scope
    )
    return Envelope[UserOut](data=UserOut.model_validate(user))


@router.delete("/users/{uid}/labels", response_model=Envelope[UserOut])
async def remove_user_label(
    uid: str,
    key: str,
    scope: str = "public",
    _admin: User = Depends(authorized_user),
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
) -> Envelope[UserOut]:
    user = await admin_service.remove_user_label(db, redis_client, uid=uid, key=key, scope=scope)
    return Envelope[UserOut](data=UserOut.model_validate(user))
