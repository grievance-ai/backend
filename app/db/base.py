"""Declarative base, naming conventions, shared column types and mixins.

All models inherit from :class:`Base`. The naming convention guarantees
deterministic constraint names so Alembic migrations downgrade cleanly.
"""

import uuid
from datetime import datetime

from sqlalchemy import CHAR, DateTime, MetaData, func
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

# Deterministic constraint names (== ARCHITECTURE §3.2)
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata_obj = MetaData(naming_convention=NAMING_CONVENTION)


class GUID(TypeDecorator[uuid.UUID]):
    """Platform-independent UUID, stored as ``CHAR(36)`` on MySQL.

    Models type as :class:`uuid.UUID`; the value is persisted as its canonical
    string form. MySQL 8 has no native UUID type (see ARCHITECTURE §3.1b).
    """

    impl = CHAR(36)
    cache_ok = True

    def process_bind_param(self, value: uuid.UUID | str | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return str(value)
        return str(uuid.UUID(value))

    def process_result_value(self, value: str | None, dialect: Dialect) -> uuid.UUID | None:
        if value is None:
            return None
        return uuid.UUID(value)


class Base(DeclarativeBase):
    metadata = metadata_obj


class TimestampMixin:
    """Adds ``created_at`` / ``updated_at`` columns, maintained by the database."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
