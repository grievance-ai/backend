"""Logic for a user managing their own account."""

import uuid
from typing import Any

import redis.asyncio as redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.errors import APIError
from app.core.tokens import TokenService
from app.models.activity import Activity
from app.models.user import User
from app.services.password_strength import password_errors


async def update_me(
    db: AsyncSession, user: User, *, username: str | None, data: dict[str, Any] | None
) -> User:
    if username is not None and username != user.username:
        taken = await db.scalar(select(User).where(User.username == username))
        if taken is not None:
            raise APIError(["resource.user.username_taken"], 409)
        user.username = username
    if data is not None:
        user.data = data
    await db.commit()
    await db.refresh(user)
    return user


async def change_password(
    db: AsyncSession,
    redis_client: redis.Redis,
    user: User,
    *,
    old_password: str,
    new_password: str,
) -> None:
    if user.password_digest is None or not security.verify_password(
        old_password, user.password_digest
    ):
        raise APIError(["resource.user.invalid_password"], 401)
    errors = password_errors(new_password)
    if errors:
        raise APIError(errors, 422)
    user.password_digest = security.hash_password(new_password)
    await db.commit()
    await TokenService(redis_client).invalidate_all(str(user.id))  # log out everywhere


async def list_activity(db: AsyncSession, user_id: uuid.UUID, topic: str) -> list[Activity]:
    rows = await db.scalars(
        select(Activity)
        .where(Activity.user_id == user_id, Activity.topic == topic)
        .order_by(Activity.created_at.desc())
        .limit(100)
    )
    return list(rows.all())
