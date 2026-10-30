"""Consent record — append-only log of what a citizen agreed to, and when."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import GUID, Base


class ConsentRecord(Base):
    __tablename__ = "consent_records"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    consent_version: Mapped[str] = mapped_column(String(20))  # e.g. "2026-10-v1"
    scope: Mapped[str] = mapped_column(String(50))  # e.g. "data_processing", "voice_recording"
    granted: Mapped[bool] = mapped_column(Boolean)  # False = withdrawn
    ip: Mapped[str | None] = mapped_column(String(45), default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
