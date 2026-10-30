"""Load the scheme knowledge base from ``config/knowledge/schemes.yml``.

Idempotent: departments upsert by ``code``, schemes by ``slug``; a scheme's
eligibility conditions are replaced wholesale on each load.
"""

from pathlib import Path
from typing import Any, cast

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enums import SchemeReviewStatus
from app.models.geography import Department, District
from app.models.grievance import GrievanceCategory
from app.models.scheme import Scheme, SchemeEligibilityCondition

KNOWLEDGE_PATH = Path("config/knowledge/schemes.yml")
GEOGRAPHY_PATH = Path("config/knowledge/punjab.yml")
GRIEVANCE_PATH = Path("config/knowledge/grievance_categories.yml")

_SCHEME_FIELDS = (
    "name",
    "short_name",
    "name_pa",
    "administering_body",
    "level",
    "state_code",
    "description",
    "benefits",
    "required_documents",
    "application_steps",
    "application_mode",
    "deadline_info",
    "official_url",
    "contact",
    "category_tags",
    "keywords",
    "last_verified_on",
    "source_name",
    "source_url",
)


async def seed_geography(db: AsyncSession, data: dict[str, Any] | None = None) -> int:
    """Upsert districts by ``code``. Returns the number of districts in the file."""
    data = data if data is not None else load_file(GEOGRAPHY_PATH)
    state = data.get("state_code", "PB")
    for row in data.get("districts", []):
        district = await db.scalar(select(District).where(District.code == row["code"]))
        if district is None:
            district = District(code=row["code"])
            db.add(district)
        district.state_code = state
        district.name_en = row["name_en"]
        district.name_pa = row.get("name_pa")
        district.is_active = row.get("is_active", True)
    await db.commit()
    return len(data.get("districts", []))


async def _upsert_departments(
    db: AsyncSession, rows: list[dict[str, Any]]
) -> dict[str, Department]:
    departments: dict[str, Department] = {}
    for row in rows:
        dept = await db.scalar(select(Department).where(Department.code == row["code"]))
        if dept is None:
            dept = Department(code=row["code"])
            db.add(dept)
        dept.name_en = row["name_en"]
        dept.name_pa = row.get("name_pa")
        departments[dept.code] = dept
    await db.flush()
    return departments


async def seed_grievance_categories(db: AsyncSession, data: dict[str, Any] | None = None) -> int:
    """Upsert grievance departments and the category tree. Returns category count."""
    data = data if data is not None else load_file(GRIEVANCE_PATH)
    departments = await _upsert_departments(db, data.get("departments", []))

    async def upsert(row: dict[str, Any], order: int, parent: GrievanceCategory | None) -> None:
        category = await db.scalar(
            select(GrievanceCategory).where(GrievanceCategory.code == row["code"])
        )
        if category is None:
            category = GrievanceCategory(code=row["code"])
            db.add(category)
        dept_code = row.get("department") or (
            parent.department.code if parent and parent.department else None
        )
        category.parent = parent
        category.name_en = row["name_en"]
        category.name_pa = row.get("name_pa")
        category.department = departments.get(dept_code) if dept_code else None
        category.sla_days = row.get("sla_days") or (parent.sla_days if parent else 15)
        category.keywords = row.get("keywords")
        category.is_active = row.get("is_active", True)
        category.sort_order = order
        await db.flush()
        for i, child in enumerate(row.get("subcategories", [])):
            await upsert(child, i, category)

    for i, row in enumerate(data.get("categories", [])):
        await upsert(row, i, None)
    await db.commit()
    return len(data.get("categories", []))


def load_file(path: Path = KNOWLEDGE_PATH) -> dict[str, Any]:
    return cast("dict[str, Any]", yaml.safe_load(path.read_text(encoding="utf-8")) or {})


def _scheme_changed(
    scheme: Scheme,
    row: dict[str, Any],
    department: Department | None,
    conditions: list[tuple[Any, ...]],
) -> bool:
    """Whether the file's version of an existing scheme differs from the database."""
    for field in _SCHEME_FIELDS:
        if field == "last_verified_on" or field not in row:
            continue
        if getattr(scheme, field) != row[field]:
            return True
    if scheme.department_id != (department.id if department else None):
        return True
    if scheme.is_active != row.get("is_active", True):
        return True
    current = [
        (c.field_name, c.operator, c.value, c.description, c.description_pa, c.group_key)
        for c in scheme.conditions
    ]
    return current != conditions


async def seed_knowledge(db: AsyncSession, data: dict[str, Any] | None = None) -> tuple[int, int]:
    """Upsert departments and schemes. Returns (departments, schemes) counts."""
    data = data if data is not None else load_file()

    departments = await _upsert_departments(db, data.get("departments", []))

    for row in data.get("schemes", []):
        scheme = await db.scalar(
            select(Scheme)
            .where(Scheme.slug == row["slug"])
            .options(selectinload(Scheme.conditions))
        )
        is_new = scheme is None
        if scheme is None:
            scheme = Scheme(slug=row["slug"])
            db.add(scheme)
        dept_code = row.get("department")
        department = departments.get(dept_code) if dept_code else None
        conditions = [
            (
                c["field"],
                c["operator"],
                c["value"],
                c["description"],
                c.get("description_pa"),
                c.get("group"),
            )
            for c in row.get("conditions", [])
        ]
        changed = is_new or _scheme_changed(scheme, row, department, conditions)

        for field in _SCHEME_FIELDS:
            # A date set by an administrator in the app is kept unless the file sets one.
            if field in row and not (field == "last_verified_on" and row[field] is None):
                setattr(scheme, field, row[field])
        scheme.department = department
        scheme.is_active = row.get("is_active", True)

        # Verified only once a person has checked it against the official source:
        # in the file (last_verified_on / review_status) or on the admin Schemes page.
        # A scheme whose content changed goes back to needs_review.
        if row.get("review_status"):
            scheme.review_status = row["review_status"]
        elif row.get("last_verified_on"):
            scheme.review_status = SchemeReviewStatus.verified.value
        elif changed:
            scheme.review_status = SchemeReviewStatus.needs_review.value

        if changed:
            scheme.conditions = [
                SchemeEligibilityCondition(
                    field_name=field_name,
                    operator=operator,
                    value=value,
                    description=description,
                    description_pa=description_pa,
                    is_mandatory=group is None,
                    group_key=group,
                    sort_order=i,
                )
                for i, (field_name, operator, value, description, description_pa, group) in (
                    enumerate(conditions)
                )
            ]

    await db.commit()
    return len(data.get("departments", [])), len(data.get("schemes", []))
