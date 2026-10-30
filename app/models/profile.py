"""User profile — personal details (PII; fields encrypted at rest in Phase 3)."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.encryption import EncryptedString
from app.db.base import GUID, Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class Profile(Base, TimestampMixin):
    __tablename__ = "profiles"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    # Encrypted at rest (Phase 3); stored as ciphertext, hence Text.
    first_name: Mapped[str | None] = mapped_column(EncryptedString(), default=None)
    last_name: Mapped[str | None] = mapped_column(EncryptedString(), default=None)
    dob: Mapped[str | None] = mapped_column(EncryptedString(), default=None)
    address: Mapped[str | None] = mapped_column(EncryptedString(), default=None)
    city: Mapped[str | None] = mapped_column(EncryptedString(), default=None)

    country: Mapped[str | None] = mapped_column(String(2), default=None)
    state: Mapped[int | None] = mapped_column(Integer, default=None)  # int-coded enum

    user: Mapped["User"] = relationship(back_populates="profiles")
