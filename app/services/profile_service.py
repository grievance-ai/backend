"""Profile management (PII fields are encrypted at rest by the column type)."""

import uuid
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.profile import Profile
from app.models.user import User


async def get_profile(db: AsyncSession, user_id: uuid.UUID) -> Profile | None:
    return cast(
        "Profile | None", await db.scalar(select(Profile).where(Profile.user_id == user_id))
    )


async def upsert_profile(
    db: AsyncSession,
    user: User,
    *,
    first_name: str | None,
    last_name: str | None,
    dob: str | None,
    address: str | None,
    city: str | None,
    country: str | None,
    state: int | None,
) -> Profile:
    profile = await get_profile(db, user.id)
    if profile is None:
        profile = Profile(user_id=user.id)
        db.add(profile)
    profile.first_name = first_name
    profile.last_name = last_name
    profile.dob = dob
    profile.address = address
    profile.city = city
    profile.country = country
    profile.state = state
    await db.commit()
    await db.refresh(profile)
    return profile
