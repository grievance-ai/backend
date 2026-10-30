"""Phone number — encrypted, with a blind index for lookups by value."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.encryption import EncryptedString
from app.db.base import GUID, Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class Phone(Base, TimestampMixin):
    __tablename__ = "phones"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    country: Mapped[str | None] = mapped_column(String(2), default=None)
    number: Mapped[str] = mapped_column(EncryptedString())  # encrypted at rest
    number_index: Mapped[str] = mapped_column(String(64))  # blind index (HMAC-SHA256)
    code: Mapped[str | None] = mapped_column(String(10), default=None)  # verification code
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    user: Mapped["User"] = relationship(back_populates="phones")

    __table_args__ = (Index("ix_phones_number_index", "number_index"),)
