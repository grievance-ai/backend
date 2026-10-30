"""DataStorage — an encrypted key/value record owned by a user."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.encryption import EncryptedString
from app.db.base import GUID, Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class DataStorage(Base, TimestampMixin):
    __tablename__ = "data_storages"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    data: Mapped[str] = mapped_column(EncryptedString())  # encrypted at rest

    user: Mapped["User"] = relationship(back_populates="data_storages")

    __table_args__ = (UniqueConstraint("user_id", "title", name="uq_data_storages_user_id_title"),)
