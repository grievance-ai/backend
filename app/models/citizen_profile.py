"""Citizen profile — self-declared attributes the scheme assistant personalises on.

One row per citizen user. Every attribute is optional: a fuller profile gives
better scheme matches, and the assistant asks for what's missing. Values are
self-declared (no document verification in the prototype).
"""

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import GUID, Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.geography import District, Tehsil
    from app.models.user import User


class CitizenProfile(Base, TimestampMixin):
    __tablename__ = "citizen_profiles"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )

    # Location
    district_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("districts.id", ondelete="SET NULL"), default=None, index=True
    )
    tehsil_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("tehsils.id", ondelete="SET NULL"), default=None
    )
    village: Mapped[str | None] = mapped_column(String(120), default=None)  # village / town
    area_type: Mapped[str | None] = mapped_column(String(10), default=None)  # AreaType

    # Eligibility-relevant attributes (field names match SchemeEligibilityCondition.field_name)
    occupation: Mapped[str | None] = mapped_column(String(64), default=None)  # e.g. "farmer"
    land_holding_acres: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), default=None)
    income_band: Mapped[str | None] = mapped_column(String(20), default=None)  # IncomeBand
    social_category: Mapped[str | None] = mapped_column(String(10), default=None)  # SocialCategory
    gender: Mapped[str | None] = mapped_column(String(15), default=None)  # Gender
    marital_status: Mapped[str | None] = mapped_column(String(15), default=None)  # MaritalStatus
    birth_year: Mapped[int | None] = mapped_column(Integer, default=None)  # for age-based schemes
    # Less common flags, e.g. {"is_bpl": true, "has_disability": false, "ration_card": "AAY"}
    extra_attributes: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)

    user: Mapped["User"] = relationship(back_populates="citizen_profile")
    district: Mapped["District | None"] = relationship()
    tehsil: Mapped["Tehsil | None"] = relationship()
