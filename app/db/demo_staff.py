"""Demo officer and administrator accounts from ``config/knowledge/demo_staff.yml``.

Idempotent. Staff log in like citizens (mobile + prototype OTP), so this only
creates the user rows and their jurisdiction. Refuses to run in production and
never turns an existing citizen into staff.
"""

from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.knowledge import load_file
from app.models.enums import Role, StaffScope, UserState
from app.models.geography import Department, District
from app.models.staff_profile import StaffProfile
from app.models.user import User
from app.services.auth_service import normalize_mobile

DEMO_STAFF_PATH = Path("config/knowledge/demo_staff.yml")
_STAFF_ROLES = {Role.officer.value, Role.admin.value, Role.superadmin.value}


async def seed_demo_staff(
    db: AsyncSession, data: dict[str, Any] | None = None
) -> tuple[int, list[str]]:
    """Returns (accounts in place, skipped mobiles)."""
    if settings.is_production:
        return 0, []
    data = data if data is not None else load_file(DEMO_STAFF_PATH)
    done, skipped = 0, []
    for row in data.get("staff", []):
        mobile = normalize_mobile(str(row["mobile"]))
        role = row["role"]
        if role not in _STAFF_ROLES or row.get("scope_level") not in {s.value for s in StaffScope}:
            raise ValueError(f"demo staff {mobile}: bad role or scope_level")

        user = await db.scalar(select(User).where(User.mobile == mobile))
        if user is None:
            user = User(mobile=mobile, role=role, state=UserState.active.value)
            db.add(user)
        elif user.role not in _STAFF_ROLES:
            skipped.append(mobile)  # a citizen already uses this number
            continue
        user.name = row.get("name")
        user.preferred_language = row.get("language", "en")
        await db.flush()

        district = None
        if row.get("district"):
            district = await db.scalar(select(District).where(District.code == row["district"]))
            if district is None:
                raise ValueError(f"demo staff {mobile}: unknown district {row['district']}")
        department = None
        if row.get("department"):
            department = await db.scalar(
                select(Department).where(Department.code == row["department"])
            )
            if department is None:
                raise ValueError(f"demo staff {mobile}: unknown department {row['department']}")

        profile = await db.scalar(select(StaffProfile).where(StaffProfile.user_id == user.id))
        if profile is None:
            profile = StaffProfile(user_id=user.id)
            db.add(profile)
        profile.designation = row.get("designation")
        profile.scope_level = row["scope_level"]
        profile.state_code = row.get("state_code", "PB")
        profile.district_id = district.id if district else None
        profile.department_id = department.id if department else None
        profile.tehsil_id = None
        profile.is_active = True
        done += 1
    await db.commit()
    return done, skipped
