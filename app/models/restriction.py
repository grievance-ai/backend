"""Restriction — IP/geo access control and maintenance switches."""

import uuid

from sqlalchemy import Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import GUID, Base, TimestampMixin
from app.models.enums import RestrictionState


class Restriction(Base, TimestampMixin):
    __tablename__ = "restrictions"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    category: Mapped[str] = mapped_column(String(20))  # whitelist/blacklist/...
    scope: Mapped[str] = mapped_column(String(20))  # ip/ip_subnet/country/...
    value: Mapped[str] = mapped_column(String(64))
    code: Mapped[int | None] = mapped_column(Integer, default=None)  # HTTP status
    state: Mapped[str] = mapped_column(String(20), default=RestrictionState.enabled.value)

    __table_args__ = (Index("ix_restrictions_scope_value", "scope", "value"),)
