"""Service account — a machine identity owned by a user."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import GUID, Base, TimestampMixin
from app.models.enums import DEFAULT_SERVICE_ACCOUNT_ROLE, AccountState
from app.utils.uid import generate_uid

if TYPE_CHECKING:
    from app.models.user import User


class ServiceAccount(Base, TimestampMixin):
    __tablename__ = "service_accounts"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    uid: Mapped[str] = mapped_column(String(32), unique=True, default=generate_uid)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), default=None, index=True
    )
    email: Mapped[str] = mapped_column(String(255), unique=True)
    role: Mapped[str] = mapped_column(String(50), default=DEFAULT_SERVICE_ACCOUNT_ROLE)
    level: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str] = mapped_column(String(50), default=AccountState.pending.value)

    owner: Mapped["User | None"] = relationship(back_populates="service_accounts")
