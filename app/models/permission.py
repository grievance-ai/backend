"""Permission — RBAC rule matched by role + HTTP verb + path prefix."""

import uuid

from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import GUID, Base, TimestampMixin
from app.models.enums import PermissionAction


class Permission(Base, TimestampMixin):
    __tablename__ = "permissions"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    role: Mapped[str] = mapped_column(String(50))
    verb: Mapped[str] = mapped_column(String(10))  # GET/POST/.../ALL
    path: Mapped[str] = mapped_column(String(255))  # path prefix
    action: Mapped[str] = mapped_column(String(10), default=PermissionAction.drop.value)
    topic: Mapped[str | None] = mapped_column(String(100), default=None)

    __table_args__ = (Index("ix_permissions_role", "role"),)
