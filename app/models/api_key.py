"""API key — HMAC credential for programmatic access (polymorphic holder)."""

import uuid

from sqlalchemy import JSON, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.encryption import EncryptedString
from app.db.base import GUID, Base, TimestampMixin
from app.models.enums import DEFAULT_API_KEY_ALGORITHM, APIKeyState


class APIKey(Base, TimestampMixin):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    kid: Mapped[str] = mapped_column(String(64), unique=True)
    algorithm: Mapped[str] = mapped_column(String(10), default=DEFAULT_API_KEY_ALGORITHM)
    scope: Mapped[list[str] | None] = mapped_column(JSON, default=None)
    secret: Mapped[str] = mapped_column(EncryptedString())  # encrypted at rest
    state: Mapped[str] = mapped_column(String(20), default=APIKeyState.active.value)

    # Polymorphic owner (User or ServiceAccount); no FK because it spans tables.
    key_holder_account_id: Mapped[uuid.UUID] = mapped_column(GUID())
    key_holder_account_type: Mapped[str] = mapped_column(String(50))

    __table_args__ = (
        Index(
            "ix_api_keys_key_holder",
            "key_holder_account_id",
            "key_holder_account_type",
        ),
    )
