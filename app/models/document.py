"""Identity document — encrypted number with a blind index, private file ref."""

import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.encryption import EncryptedString
from app.db.base import GUID, Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    doc_type: Mapped[str] = mapped_column(String(50))
    doc_number: Mapped[str] = mapped_column(EncryptedString())  # encrypted at rest
    doc_number_index: Mapped[str] = mapped_column(String(64))  # blind index
    upload: Mapped[str | None] = mapped_column(String(255), default=None)  # storage key
    doc_expire: Mapped[date | None] = mapped_column(Date, default=None)
    identificator: Mapped[str | None] = mapped_column(String(64), default=None)

    user: Mapped["User"] = relationship(back_populates="documents")

    __table_args__ = (Index("ix_documents_doc_number_index", "doc_number_index"),)
