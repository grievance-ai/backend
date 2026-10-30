"""Scheme knowledge base — the curated dataset the assistant answers from.

Eligibility is stored as one row per condition (field, operator, value) so the
assistant can say exactly which conditions a citizen meets or misses. When a
condition's ``field_name`` matches a ``CitizenProfile`` attribute it can be
checked automatically; otherwise (e.g. ``crop_loss_cause``) it is answered from
the conversation.
"""

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import GUID, Base, TimestampMixin
from app.models.enums import SchemeLevel

if TYPE_CHECKING:
    from app.models.geography import Department


class Scheme(Base, TimestampMixin):
    __tablename__ = "schemes"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(100), unique=True)  # e.g. "pmfby"

    # Identity
    name: Mapped[str] = mapped_column(String(255))  # official (English) name
    short_name: Mapped[str | None] = mapped_column(String(50), default=None)  # e.g. "PMFBY"
    name_pa: Mapped[str | None] = mapped_column(String(255), default=None)
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("departments.id", ondelete="SET NULL"), default=None
    )
    administering_body: Mapped[str | None] = mapped_column(String(255), default=None)
    level: Mapped[str] = mapped_column(String(10), default=SchemeLevel.central.value)
    state_code: Mapped[str | None] = mapped_column(String(5), default=None)  # null = all-India

    # Content
    description: Mapped[str] = mapped_column(Text)  # 2-3 plain-language sentences
    benefits: Mapped[str] = mapped_column(Text)  # concrete amounts / coverage
    required_documents: Mapped[list[str]] = mapped_column(JSON, default=list)
    application_steps: Mapped[list[str]] = mapped_column(JSON, default=list)  # ordered
    application_mode: Mapped[str | None] = mapped_column(String(50), default=None)  # online/office
    deadline_info: Mapped[str | None] = mapped_column(String(255), default=None)
    official_url: Mapped[str | None] = mapped_column(String(500), default=None)
    contact: Mapped[str | None] = mapped_column(Text, default=None)  # department / helpline

    # Metadata
    category_tags: Mapped[list[str]] = mapped_column(JSON, default=list)  # e.g. ["agriculture"]
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)  # en + pa match terms
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    last_verified_on: Mapped[date | None] = mapped_column(Date, default=None)  # checked vs source
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    department: Mapped["Department | None"] = relationship()
    conditions: Mapped[list["SchemeEligibilityCondition"]] = relationship(
        back_populates="scheme",
        cascade="all, delete-orphan",
        order_by="SchemeEligibilityCondition.sort_order",
    )


class SchemeEligibilityCondition(Base, TimestampMixin):
    __tablename__ = "scheme_eligibility_conditions"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    scheme_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("schemes.id", ondelete="CASCADE"), index=True
    )
    field_name: Mapped[str] = mapped_column(String(64))  # e.g. "land_holding_acres"
    operator: Mapped[str] = mapped_column(String(10))  # ConditionOperator
    value: Mapped[Any] = mapped_column(JSON)  # 5, "farmer", ["sc", "st"], ...
    description: Mapped[str] = mapped_column(String(500))  # human-readable condition
    description_pa: Mapped[str | None] = mapped_column(String(500), default=None)
    is_mandatory: Mapped[bool] = mapped_column(Boolean, default=True)  # false = "any of" group
    group_key: Mapped[str | None] = mapped_column(String(30), default=None)  # OR-groups
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    scheme: Mapped[Scheme] = relationship(back_populates="conditions")


class SchemeInterest(Base):
    """A citizen showing interest in a scheme — take-up analytics and 'saved schemes'."""

    __tablename__ = "scheme_interests"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    scheme_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("schemes.id", ondelete="CASCADE"), index=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("conversations.id", ondelete="SET NULL"), default=None
    )
    interest_type: Mapped[str] = mapped_column(String(20))  # SchemeInterestType
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    scheme: Mapped[Scheme] = relationship()

    __table_args__ = (Index("ix_scheme_interests_created_at", "created_at"),)
