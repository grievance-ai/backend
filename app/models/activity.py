"""Activity — immutable audit record (created only, never updated/deleted)."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, event, func
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from app.db.base import GUID, Base

if TYPE_CHECKING:
    from app.models.user import User


class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), default=None, index=True
    )
    target_uid: Mapped[str | None] = mapped_column(String(32), default=None)
    actor_role: Mapped[str | None] = mapped_column(String(50), default=None)
    target_type: Mapped[str | None] = mapped_column(String(50), default=None)  # e.g. "grievance"
    target_id: Mapped[str | None] = mapped_column(String(64), default=None)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)  # previous values
    after: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)  # new values
    category: Mapped[str] = mapped_column(String(50))
    user_ip: Mapped[str | None] = mapped_column(String(45), default=None)  # IPv4/IPv6
    user_ip_country: Mapped[str | None] = mapped_column(String(2), default=None)  # GeoIP
    user_agent: Mapped[str | None] = mapped_column(String(255), default=None)
    topic: Mapped[str] = mapped_column(String(100), index=True)
    action: Mapped[str] = mapped_column(String(100))
    result: Mapped[str] = mapped_column(String(20))  # succeed | failed | denied
    data: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User | None"] = relationship(back_populates="activities")

    __table_args__ = (
        Index("ix_activities_created_at", "created_at"),
        Index("ix_activities_target_type_target_id", "target_type", "target_id"),
    )


class ActivityImmutableError(RuntimeError):
    """Raised on any attempt to update or delete an audit record."""


@event.listens_for(Session, "before_flush")
def _enforce_activity_immutability(
    session: Session, flush_context: object, instances: object
) -> None:
    """Reject updates/deletes to ``Activity`` before the flush emits any SQL.

    Inserting new records is always allowed (they live in ``session.new``);
    only modifications (``session.dirty``) and deletions are blocked. Raising at
    ``before_flush`` keeps the connection clean — raising later, mid-flush, can
    trip async IO during error unwinding.
    """
    if any(isinstance(obj, Activity) for obj in session.deleted):
        raise ActivityImmutableError("activities are append-only and cannot be deleted")
    if any(isinstance(obj, Activity) and session.is_modified(obj) for obj in session.dirty):
        raise ActivityImmutableError("activities are append-only and cannot be modified")
