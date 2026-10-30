"""Reference data: administrative geography and government departments.

Seeded, rarely edited. Grievances, profiles and staff jurisdictions point here
so filters and analytics group on stable IDs, not free text.
"""

import uuid

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import GUID, Base, TimestampMixin


class District(Base, TimestampMixin):
    __tablename__ = "districts"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(10), unique=True)  # e.g. "LDH"
    state_code: Mapped[str] = mapped_column(String(5), default="PB", index=True)
    name_en: Mapped[str] = mapped_column(String(100))
    name_pa: Mapped[str | None] = mapped_column(String(100), default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    tehsils: Mapped[list["Tehsil"]] = relationship(
        back_populates="district", cascade="all, delete-orphan"
    )


class Tehsil(Base, TimestampMixin):
    __tablename__ = "tehsils"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    district_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("districts.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(20))
    name_en: Mapped[str] = mapped_column(String(100))
    name_pa: Mapped[str | None] = mapped_column(String(100), default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    district: Mapped[District] = relationship(back_populates="tehsils")

    __table_args__ = (UniqueConstraint("district_id", "code", name="uq_tehsils_district_id_code"),)


class Department(Base, TimestampMixin):
    __tablename__ = "departments"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(30), unique=True)  # e.g. "WATER_SUPPLY"
    name_en: Mapped[str] = mapped_column(String(150))
    name_pa: Mapped[str | None] = mapped_column(String(150), default=None)
    helpline: Mapped[str | None] = mapped_column(String(50), default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
