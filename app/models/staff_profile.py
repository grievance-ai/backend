"""Staff profile — jurisdiction for officers and administrators.

Scope rules:
- ``tehsil``   → sees grievances in that tehsil (and department, if set)
- ``district`` → sees the whole district (and department, if set)
- ``state``    → sees every district in ``state_code``
- ``system``   → sees everything
A null ``department_id`` means "all departments" within the geographic scope.
"""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import GUID, Base, TimestampMixin
from app.models.enums import StaffScope

if TYPE_CHECKING:
    from app.models.geography import Department, District, Tehsil
    from app.models.user import User


class StaffProfile(Base, TimestampMixin):
    __tablename__ = "staff_profiles"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    designation: Mapped[str | None] = mapped_column(String(120), default=None)  # e.g. "SDO"
    scope_level: Mapped[str] = mapped_column(String(20), default=StaffScope.district.value)
    state_code: Mapped[str] = mapped_column(String(5), default="PB")
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("departments.id", ondelete="SET NULL"), default=None, index=True
    )
    district_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("districts.id", ondelete="SET NULL"), default=None, index=True
    )
    tehsil_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("tehsils.id", ondelete="SET NULL"), default=None
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    user: Mapped["User"] = relationship(back_populates="staff_profile")
    department: Mapped["Department | None"] = relationship()
    district: Mapped["District | None"] = relationship()
    tehsil: Mapped["Tehsil | None"] = relationship()
