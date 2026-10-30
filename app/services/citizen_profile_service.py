"""Read and update the citizen's own profile (spec §5.2)."""

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.activity import log_activity
from app.core.errors import APIError
from app.models.citizen_profile import CitizenProfile
from app.models.enums import AreaType, Gender, MaritalStatus
from app.models.geography import District
from app.models.user import User
from app.schemas.citizen import CitizenProfileOut, CitizenProfileUpdate, DistrictOut


def _age(birth_year: int | None) -> int | None:
    return dt.date.today().year - birth_year if birth_year else None


async def get_or_create(db: AsyncSession, user: User) -> CitizenProfile:
    profile = await db.scalar(
        select(CitizenProfile)
        .where(CitizenProfile.user_id == user.id)
        .options(selectinload(CitizenProfile.district))
    )
    if profile is None:
        profile = CitizenProfile(user_id=user.id)
        db.add(profile)
        await db.commit()
        await db.refresh(profile, attribute_names=["district"])
    return profile


def is_complete(user: User, profile: CitizenProfile | None) -> bool:
    """The onboarding details: name, age, gender and marital status.

    District and area type are optional (Profile page only); the assistant asks
    for them when a scheme or grievance needs them.
    """
    return bool(
        profile and user.name and profile.birth_year and profile.gender and profile.marital_status
    )


def to_out(user: User, profile: CitizenProfile) -> CitizenProfileOut:
    return CitizenProfileOut(
        name=user.name,
        mobile=user.mobile,
        preferred_language=user.preferred_language,
        age=_age(profile.birth_year),
        gender=Gender(profile.gender) if profile.gender else None,
        marital_status=MaritalStatus(profile.marital_status) if profile.marital_status else None,
        district=DistrictOut.model_validate(profile.district) if profile.district else None,
        area_type=AreaType(profile.area_type) if profile.area_type else None,
        village=profile.village,
        is_complete=is_complete(user, profile),
    )


async def update(db: AsyncSession, user: User, payload: CitizenProfileUpdate) -> CitizenProfileOut:
    profile = await get_or_create(db, user)
    fields = payload.model_fields_set
    changed: list[str] = []

    if "name" in fields and payload.name is not None:
        user.name = payload.name.strip()
        changed.append("name")
    if "preferred_language" in fields and payload.preferred_language is not None:
        user.preferred_language = payload.preferred_language
        changed.append("preferred_language")
    if "age" in fields:
        profile.birth_year = dt.date.today().year - payload.age if payload.age else None
        changed.append("age")
    if "gender" in fields:
        profile.gender = payload.gender.value if payload.gender else None
        changed.append("gender")
    if "marital_status" in fields:
        profile.marital_status = payload.marital_status.value if payload.marital_status else None
        changed.append("marital_status")
    if "area_type" in fields:
        profile.area_type = payload.area_type.value if payload.area_type else None
        changed.append("area_type")
    if "village" in fields:
        profile.village = (payload.village or "").strip() or None
        changed.append("village")
    if "district_code" in fields:
        if payload.district_code:
            district = await db.scalar(
                select(District).where(
                    District.code == payload.district_code, District.is_active.is_(True)
                )
            )
            if district is None:
                raise APIError(["resource.profile.invalid_district"], 422)
            profile.district = district
        else:
            profile.district = None
        changed.append("district")

    await db.commit()
    await db.refresh(profile, attribute_names=["district"])
    if changed:
        # Field names only: the audit trail must not copy personal details.
        log_activity(
            topic="profile",
            action="update",
            result="succeed",
            category="user",
            user_id=user.id,
            actor_role=user.role,
            target_type="citizen_profile",
            target_id=str(profile.id),
            data={"fields": changed},
        )
    return to_out(user, profile)


async def list_districts(db: AsyncSession) -> list[DistrictOut]:
    rows = await db.scalars(
        select(District).where(District.is_active.is_(True)).order_by(District.name_en)
    )
    return [DistrictOut.model_validate(d) for d in rows]
