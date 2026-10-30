"""Citizen grievances: review draft, submit, and track (spec §5.8).

Submission:
- reference number ``GRV-<year>-<6 digits>`` from a row-locked counter, so two
  simultaneous submissions can never get the same number;
- routed to the category's department (subcategory first), due date from its SLA;
- flagged (never merged) as a possible duplicate when the same citizen filed the
  same category in the same district within 7 days (spec §5.9);
- first status-history entry, conversation linked and marked submitted, audit entry.
"""

import datetime as dt
import uuid
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.activity import log_activity
from app.core.errors import APIError
from app.models.citizen_profile import CitizenProfile
from app.models.conversation import Conversation
from app.models.enums import (
    ConversationMode,
    ConversationStatus,
    GrievanceEventType,
    GrievanceStatus,
    NoteVisibility,
)
from app.models.geography import District
from app.models.grievance import (
    Grievance,
    GrievanceCategory,
    GrievanceStatusHistory,
    ReferenceCounter,
)
from app.models.user import User
from app.schemas.citizen import DistrictOut
from app.schemas.grievance import (
    CategoryOut,
    CitizenUpdateOut,
    GrievanceDraftOut,
    GrievanceIn,
    GrievanceOut,
    GrievanceSummaryOut,
    NamedOut,
    StatusEventOut,
)

REFERENCE_PREFIX = "GRV"
DUPLICATE_WINDOW = dt.timedelta(days=7)


# Max characters kept per grievance-draft field. Longer values are model junk
# (a degenerate reply can dump everything into one field), so they are dropped.
DRAFT_FIELD_LIMITS = {"summary": 200, "location": 255, "since": 120, "prior_complaint": 500}


def _utc(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


# --- reference numbers ---------------------------------------------------------


async def next_reference(db: AsyncSession, *, year: int) -> str:
    """Allocate the next number for ``year`` inside the caller's transaction."""
    for _ in range(3):
        counter = await db.scalar(
            select(ReferenceCounter)
            .where(ReferenceCounter.prefix == REFERENCE_PREFIX, ReferenceCounter.year == year)
            .with_for_update()
        )
        if counter is not None:
            counter.last_value += 1
            return f"{REFERENCE_PREFIX}-{year}-{counter.last_value:06d}"
        # First grievance of the year: create the counter row (another request may
        # race us to it; then retry and lock the row it created).
        try:
            async with db.begin_nested():
                db.add(ReferenceCounter(prefix=REFERENCE_PREFIX, year=year, last_value=0))
        except IntegrityError:
            continue
    raise APIError(["resource.grievance.reference_unavailable"], 503)


# --- lookups ---------------------------------------------------------------------


async def list_categories(db: AsyncSession) -> list[CategoryOut]:
    rows = await db.scalars(
        select(GrievanceCategory)
        .where(GrievanceCategory.parent_id.is_(None), GrievanceCategory.is_active.is_(True))
        .options(
            selectinload(GrievanceCategory.department),
            selectinload(GrievanceCategory.children),
        )
        .order_by(GrievanceCategory.sort_order)
    )
    return [
        CategoryOut(
            code=c.code,
            name_en=c.name_en,
            name_pa=c.name_pa,
            department=NamedOut.model_validate(c.department) if c.department else None,
            subcategories=[
                NamedOut.model_validate(s)
                for s in sorted(c.children, key=lambda s: s.sort_order)
                if s.is_active
            ],
        )
        for c in rows
    ]


async def _category(db: AsyncSession, code: str | None) -> GrievanceCategory | None:
    if not code:
        return None
    return cast(
        "GrievanceCategory | None",
        await db.scalar(
            select(GrievanceCategory)
            .where(GrievanceCategory.code == code, GrievanceCategory.is_active.is_(True))
            .options(selectinload(GrievanceCategory.department))
        ),
    )


async def _district_by_name_or_code(db: AsyncSession, value: str | None) -> District | None:
    """The assistant reports districts as the citizen said them (English or Punjabi)."""
    if not value:
        return None
    needle = value.strip().lower()
    for district in await db.scalars(select(District).where(District.is_active.is_(True))):
        names = {district.code.lower(), district.name_en.lower(), (district.name_pa or "").lower()}
        if needle in names or any(n and n.split(" (")[0] == needle for n in names):
            return district
    return None


async def _owned_conversation(
    db: AsyncSession, user: User, conversation_id: uuid.UUID
) -> Conversation:
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise APIError(["resource.conversation.not_found"], 404)
    return conversation


# --- draft --------------------------------------------------------------------------


async def get_draft(
    db: AsyncSession, user: User, conversation_id: uuid.UUID | None
) -> GrievanceDraftOut:
    draft: dict[str, Any] = {}
    if conversation_id is not None:
        conversation = await _owned_conversation(db, user, conversation_id)
        draft = conversation.grievance_draft or {}

    category = await _category(db, draft.get("category_code"))
    subcategory = await _category(db, draft.get("subcategory_code"))
    if subcategory is not None and (category is None or subcategory.parent_id != category.id):
        subcategory = None

    district = await _district_by_name_or_code(db, draft.get("district"))
    if district is None:  # fall back to the citizen's own district
        profile = await db.scalar(
            select(CitizenProfile)
            .where(CitizenProfile.user_id == user.id)
            .options(selectinload(CitizenProfile.district))
        )
        district = profile.district if profile else None

    def text(key: str) -> str | None:
        value = str(draft.get(key) or "").strip()
        if not value or len(value) > DRAFT_FIELD_LIMITS.get(key, len(value)):
            return None  # empty, or junk from a degenerate model reply
        return value

    return GrievanceDraftOut(
        conversation_id=conversation_id,
        category_code=category.code if category else None,
        subcategory_code=subcategory.code if subcategory else None,
        district_code=district.code if district else None,
        location_detail=text("location"),
        summary=text("summary"),
        # The fallback model sometimes writes only a summary; it's a fair start
        # for the description, which the citizen can expand on the review screen.
        description=text("description") or text("summary"),
        since=text("since"),
        prior_complaint=text("prior_complaint"),
    )


# --- submit ---------------------------------------------------------------------------


async def submit(db: AsyncSession, user: User, payload: GrievanceIn) -> GrievanceOut:
    category = await _category(db, payload.category_code)
    if category is None or category.parent_id is not None:
        raise APIError(["resource.grievance.invalid_category"], 422)
    subcategory = await _category(db, payload.subcategory_code)
    if payload.subcategory_code and (subcategory is None or subcategory.parent_id != category.id):
        raise APIError(["resource.grievance.invalid_subcategory"], 422)
    district = await db.scalar(
        select(District).where(District.code == payload.district_code, District.is_active.is_(True))
    )
    if district is None:
        raise APIError(["resource.grievance.invalid_district"], 422)

    conversation = None
    if payload.conversation_id is not None:
        conversation = await _owned_conversation(db, user, payload.conversation_id)
        existing = await db.scalar(
            select(Grievance).where(Grievance.conversation_id == conversation.id)
        )
        if existing is not None:  # double tap / resubmit: return the one already filed
            return await get_mine(db, user, existing.reference_no)

    now = dt.datetime.now(dt.UTC)
    route = subcategory or category
    department = route.department or category.department
    duplicate = await db.scalar(
        select(Grievance)
        .where(
            Grievance.user_id == user.id,
            Grievance.category_id == category.id,
            Grievance.district_id == district.id,
            Grievance.submitted_at >= now - DUPLICATE_WINDOW,
        )
        .order_by(Grievance.submitted_at.desc())
        .limit(1)
    )
    description = payload.description.strip()

    grievance = Grievance(
        reference_no=await next_reference(db, year=now.year),
        user_id=user.id,
        conversation_id=conversation.id if conversation else None,
        language=conversation.language if conversation else user.preferred_language,
        category_id=category.id,
        subcategory_id=subcategory.id if subcategory else None,
        department_id=department.id if department else None,
        district_id=district.id,
        location_detail=(payload.location_detail or "").strip() or None,
        summary=((payload.summary or "").strip() or description)[:255],
        description=description,
        extra_fields={"since": payload.since.strip()} if payload.since else None,
        prior_complaint=(payload.prior_complaint or "").strip() or None,
        status=GrievanceStatus.new.value,
        submitted_at=now,
        due_at=now + dt.timedelta(days=route.sla_days or category.sla_days),
        possible_duplicate_of_id=duplicate.id if duplicate else None,
    )
    db.add(grievance)
    await db.flush()
    db.add(
        GrievanceStatusHistory(
            grievance_id=grievance.id,
            event_type=GrievanceEventType.status_change.value,
            from_status=None,
            to_status=GrievanceStatus.new.value,
            changed_by_id=user.id,
            created_at=now,
        )
    )
    if conversation is not None:
        conversation.mode = ConversationMode.grievance_intake.value
        conversation.status = ConversationStatus.grievance_submitted.value
    await db.commit()

    log_activity(
        topic="grievance",
        action="submit",
        result="succeed",
        category="user",
        user_id=user.id,
        actor_role=user.role,
        target_type="grievance",
        target_id=grievance.reference_no,
        after={
            "status": grievance.status,
            "category": category.code,
            "district": district.code,
            "possible_duplicate_of": duplicate.reference_no if duplicate else None,
        },
    )
    return await get_mine(db, user, grievance.reference_no)


# --- tracking ----------------------------------------------------------------------------


def _summary(g: Grievance) -> GrievanceSummaryOut:
    return GrievanceSummaryOut(
        reference_no=g.reference_no,
        status=g.status,
        summary=g.summary,
        category=NamedOut.model_validate(g.category),
        district=DistrictOut.model_validate(g.district),
        submitted_at=cast("dt.datetime", _utc(g.submitted_at)),
        due_at=_utc(g.due_at),
    )


async def list_mine(db: AsyncSession, user: User) -> list[GrievanceSummaryOut]:
    rows = await db.scalars(
        select(Grievance)
        .where(Grievance.user_id == user.id)
        .options(selectinload(Grievance.category), selectinload(Grievance.district))
        .order_by(Grievance.submitted_at.desc())
        .limit(50)
    )
    return [_summary(g) for g in rows]


async def get_mine(db: AsyncSession, user: User, reference_no: str) -> GrievanceOut:
    g = await db.scalar(
        select(Grievance)
        .where(Grievance.reference_no == reference_no, Grievance.user_id == user.id)
        .options(
            selectinload(Grievance.category),
            selectinload(Grievance.subcategory),
            selectinload(Grievance.department),
            selectinload(Grievance.district),
            selectinload(Grievance.possible_duplicate_of),
            selectinload(Grievance.history),
            selectinload(Grievance.notes),
        )
        .execution_options(populate_existing=True)
    )
    if g is None:
        raise APIError(["resource.grievance.not_found"], 404)
    return GrievanceOut(
        **_summary(g).model_dump(),
        subcategory=NamedOut.model_validate(g.subcategory) if g.subcategory else None,
        department=NamedOut.model_validate(g.department) if g.department else None,
        location_detail=g.location_detail,
        description=g.description,
        since=(g.extra_fields or {}).get("since"),
        prior_complaint=g.prior_complaint,
        language=g.language,
        possible_duplicate_of=g.possible_duplicate_of.reference_no
        if g.possible_duplicate_of
        else None,
        history=[
            StatusEventOut(
                to_status=h.to_status,
                remark=h.remark,
                created_at=cast("dt.datetime", _utc(h.created_at)),
            )
            for h in g.history
            if h.event_type == GrievanceEventType.status_change.value
        ],
        updates=[
            CitizenUpdateOut(content=n.content, created_at=cast("dt.datetime", _utc(n.created_at)))
            for n in g.notes
            if n.visibility == NoteVisibility.citizen.value
        ],
    )
