"""Public labels a user manages on their own account.

Private labels (email/phone/document verified, bans, …) are system-managed and
are not exposed through these endpoints.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.emails import dispatch
from app.models.enums import LabelScope
from app.models.label import Label
from app.models.user import User


async def list_public_labels(db: AsyncSession, user_id: uuid.UUID) -> list[Label]:
    rows = await db.scalars(
        select(Label).where(Label.user_id == user_id, Label.scope == LabelScope.public.value)
    )
    return list(rows.all())


async def create_public_label(db: AsyncSession, user: User, *, key: str, value: str) -> Label:
    existing = await db.scalar(
        select(Label).where(
            Label.user_id == user.id,
            Label.key == key,
            Label.scope == LabelScope.public.value,
        )
    )
    if existing is not None:
        raise APIError(["resource.label.exists"], 409)
    label = Label(user_id=user.id, key=key, value=value, scope=LabelScope.public.value)
    db.add(label)
    await db.commit()
    await db.refresh(label)
    dispatch.send_label_email(user, key=key, value=value)
    return label
