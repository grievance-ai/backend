"""The authenticated user's own account: profile basics, password, activity."""

import redis.asyncio as redis
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import authorized_user, get_redis
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import Envelope, Message
from app.schemas.identity import UserOut
from app.schemas.resource import ActivityOut, ChangePasswordIn, UserUpdateIn
from app.services import user_service

router = APIRouter()


@router.get("/users/me", response_model=Envelope[UserOut])
async def get_me(user: User = Depends(authorized_user)) -> Envelope[UserOut]:
    return Envelope[UserOut](data=UserOut.model_validate(user))


@router.put("/users/me", response_model=Envelope[UserOut])
async def update_me(
    payload: UserUpdateIn,
    user: User = Depends(authorized_user),
    db: AsyncSession = Depends(get_db),
) -> Envelope[UserOut]:
    updated = await user_service.update_me(db, user, username=payload.username, data=payload.data)
    return Envelope[UserOut](data=UserOut.model_validate(updated))


@router.put("/users/password", response_model=Envelope[Message])
async def change_password(
    payload: ChangePasswordIn,
    user: User = Depends(authorized_user),
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
) -> Envelope[Message]:
    await user_service.change_password(
        db, redis_client, user, old_password=payload.old_password, new_password=payload.new_password
    )
    return Envelope[Message](data=Message(message="Password updated."))


@router.get("/users/activity/{topic}", response_model=Envelope[list[ActivityOut]])
async def get_activity(
    topic: str,
    user: User = Depends(authorized_user),
    db: AsyncSession = Depends(get_db),
) -> Envelope[list[ActivityOut]]:
    rows = await user_service.list_activity(db, user.id, topic)
    return Envelope[list[ActivityOut]](data=[ActivityOut.model_validate(r) for r in rows])
