"""Label — a verified attribute that drives a user's level and state."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import GUID, Base, TimestampMixin
from app.models.enums import LabelScope

if TYPE_CHECKING:
    from app.models.user import User


class Label(Base, TimestampMixin):
    __tablename__ = "labels"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    key: Mapped[str] = mapped_column(String(255))
    value: Mapped[str] = mapped_column(String(255))
    scope: Mapped[str] = mapped_column(String(50), default=LabelScope.public.value)

    user: Mapped["User"] = relationship(back_populates="labels")

    __table_args__ = (
        UniqueConstraint("user_id", "key", "scope", name="uq_labels_user_id_key_scope"),
        Index("ix_labels_key_value", "key", "value"),
    )
