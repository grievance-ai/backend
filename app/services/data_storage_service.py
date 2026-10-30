"""Per-user encrypted key/value storage."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.models.data_storage import DataStorage
from app.models.user import User


async def list_items(db: AsyncSession, user_id: uuid.UUID) -> list[DataStorage]:
    rows = await db.scalars(select(DataStorage).where(DataStorage.user_id == user_id))
    return list(rows.all())


async def create_item(db: AsyncSession, user: User, *, title: str, data: str) -> DataStorage:
    existing = await db.scalar(
        select(DataStorage).where(DataStorage.user_id == user.id, DataStorage.title == title)
    )
    if existing is not None:
        raise APIError(["resource.data_storage.exists"], 409)
    item = DataStorage(user_id=user.id, title=title, data=data)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item
