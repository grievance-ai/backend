"""Comment — an admin note attached to a user."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import GUID, Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class Comment(Base, TimestampMixin):
    __tablename__ = "comments"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    author_uid: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(255))
    data: Mapped[str] = mapped_column(Text)

    user: Mapped["User"] = relationship(back_populates="comments", foreign_keys=[user_id])
