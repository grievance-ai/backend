"""Grievances and the officer workflow around them.

Lifecycle: new → assigned → under_verification → in_progress → resolved → closed,
with reopened from resolved/closed. Allowed transitions are enforced in the
service layer; every change is written to ``grievance_status_history``.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import GUID, Base, TimestampMixin
from app.models.enums import GrievancePriority, GrievanceStatus, Language, NoteVisibility

if TYPE_CHECKING:
    from app.models.conversation import Conversation
    from app.models.geography import Department, District, Tehsil
    from app.models.user import User


class GrievanceCategory(Base, TimestampMixin):
    """Category tree (top level + subcategories), each mapped to a department for routing."""

    __tablename__ = "grievance_categories"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("grievance_categories.id", ondelete="CASCADE"), default=None, index=True
    )
    code: Mapped[str] = mapped_column(String(50), unique=True)  # e.g. "WATER_SUPPLY_DISRUPTION"
    name_en: Mapped[str] = mapped_column(String(150))
    name_pa: Mapped[str | None] = mapped_column(String(150), default=None)
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("departments.id", ondelete="SET NULL"), default=None
    )
    sla_days: Mapped[int] = mapped_column(Integer, default=15)  # sets Grievance.due_at
    # Extra fields the assistant should collect for this category, e.g.
    # [{"key": "connection_number", "label": "Water connection number", "required": false}]
    extra_fields_schema: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, default=None)
    keywords: Mapped[list[str] | None] = mapped_column(JSON, default=None)  # classification hints
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    parent: Mapped["GrievanceCategory | None"] = relationship(
        remote_side="GrievanceCategory.id", back_populates="children"
    )
    children: Mapped[list["GrievanceCategory"]] = relationship(back_populates="parent")
    department: Mapped["Department | None"] = relationship()


class Grievance(Base, TimestampMixin):
    __tablename__ = "grievances"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    reference_no: Mapped[str] = mapped_column(String(20), unique=True)  # GRV-2026-000123

    # Who and where it came from
    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("users.id"), index=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("conversations.id", ondelete="SET NULL"), default=None
    )
    language: Mapped[str] = mapped_column(String(5), default=Language.pa.value)

    # Classification and routing
    category_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("grievance_categories.id"), index=True
    )
    subcategory_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("grievance_categories.id", ondelete="SET NULL"), default=None
    )
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("departments.id", ondelete="SET NULL"), default=None, index=True
    )
    district_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("districts.id"))
    tehsil_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("tehsils.id", ondelete="SET NULL"), default=None
    )
    location_detail: Mapped[str | None] = mapped_column(String(255), default=None)  # mohalla/ward

    # What happened
    summary: Mapped[str] = mapped_column(String(255))  # one-line title for the officer queue
    description: Mapped[str] = mapped_column(Text)
    extra_fields: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    prior_complaint: Mapped[str | None] = mapped_column(Text, default=None)  # already complained?

    # Workflow
    status: Mapped[str] = mapped_column(String(25), default=GrievanceStatus.new.value)
    priority: Mapped[str] = mapped_column(String(10), default=GrievancePriority.normal.value)
    assigned_officer_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), default=None, index=True
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    reopen_count: Mapped[int] = mapped_column(Integer, default=0)
    resolution_outcome: Mapped[str | None] = mapped_column(String(30), default=None)
    resolution_note: Mapped[str | None] = mapped_column(Text, default=None)

    # Possible duplicate: same citizen + category + district within 7 days. Flag only.
    possible_duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("grievances.id", ondelete="SET NULL"), default=None
    )

    citizen: Mapped["User"] = relationship(foreign_keys=[user_id])
    assigned_officer: Mapped["User | None"] = relationship(foreign_keys=[assigned_officer_id])
    conversation: Mapped["Conversation | None"] = relationship()
    category: Mapped[GrievanceCategory] = relationship(foreign_keys=[category_id])
    subcategory: Mapped[GrievanceCategory | None] = relationship(foreign_keys=[subcategory_id])
    department: Mapped["Department | None"] = relationship()
    district: Mapped["District"] = relationship()
    tehsil: Mapped["Tehsil | None"] = relationship()
    possible_duplicate_of: Mapped["Grievance | None"] = relationship(remote_side="Grievance.id")
    history: Mapped[list["GrievanceStatusHistory"]] = relationship(
        back_populates="grievance",
        cascade="all, delete-orphan",
        order_by="GrievanceStatusHistory.created_at",
    )
    notes: Mapped[list["GrievanceNote"]] = relationship(
        back_populates="grievance",
        cascade="all, delete-orphan",
        order_by="GrievanceNote.created_at",
    )
    attachments: Mapped[list["GrievanceAttachment"]] = relationship(
        back_populates="grievance", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # Officer queue filters
        Index("ix_grievances_district_id_status", "district_id", "status"),
        Index("ix_grievances_status_submitted_at", "status", "submitted_at"),
        # Duplicate check
        Index(
            "ix_grievances_user_id_category_id_district_id",
            "user_id",
            "category_id",
            "district_id",
        ),
    )


# Microsecond precision: an officer's first action writes the assignment and the
# status change in the same second, and the timeline must keep their order.
PRECISE_DATETIME = DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql")


class GrievanceStatusHistory(Base):
    """Every status change and (re)assignment, with who did it and why."""

    __tablename__ = "grievance_status_history"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    grievance_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("grievances.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(20))  # GrievanceEventType
    from_status: Mapped[str | None] = mapped_column(String(25), default=None)
    to_status: Mapped[str | None] = mapped_column(String(25), default=None)
    from_officer_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    to_officer_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    changed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    remark: Mapped[str | None] = mapped_column(Text, default=None)  # required for resolve/close
    created_at: Mapped[datetime] = mapped_column(
        PRECISE_DATETIME, server_default=func.now(6), nullable=False
    )

    grievance: Mapped[Grievance] = relationship(back_populates="history")
    changed_by: Mapped["User | None"] = relationship(foreign_keys=[changed_by_id])


class GrievanceNote(Base, TimestampMixin):
    """Internal officer notes, or updates the citizen sees when looking up the reference."""

    __tablename__ = "grievance_notes"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    grievance_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("grievances.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    visibility: Mapped[str] = mapped_column(String(10), default=NoteVisibility.internal.value)
    content: Mapped[str] = mapped_column(Text)

    grievance: Mapped[Grievance] = relationship(back_populates="notes")
    author: Mapped["User | None"] = relationship()


class GrievanceAttachment(Base, TimestampMixin):
    __tablename__ = "grievance_attachments"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    grievance_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("grievances.id", ondelete="CASCADE"), index=True
    )
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    storage_key: Mapped[str] = mapped_column(String(255))  # via app.integrations.storage
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)

    grievance: Mapped[Grievance] = relationship(back_populates="attachments")


class ReferenceCounter(Base):
    """Per-prefix, per-year sequence for readable reference numbers (GRV-2026-000123).

    Incremented with ``SELECT ... FOR UPDATE`` so concurrent submissions never collide.
    """

    __tablename__ = "reference_counters"

    prefix: Mapped[str] = mapped_column(String(10), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_value: Mapped[int] = mapped_column(Integer, default=0)
