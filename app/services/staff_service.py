"""Officer queue, grievance handling and the administrator overview (spec §5.9, §5.10).

Jurisdiction (``StaffProfile``) is applied to every query here, never in the UI:
- superadmin sees everything;
- officers and administrators need an active staff profile; its scope level
  (tehsil / district / state / system) and optional department narrow what they see.
A grievance outside the caller's jurisdiction answers 404, so its existence never leaks.
"""

import datetime as dt
import uuid
from typing import Any, cast

from sqlalchemy import ColumnElement, Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.activity import log_activity
from app.core.errors import APIError
from app.models.citizen_profile import CitizenProfile
from app.models.conversation import (
    Conversation,
    ConversationMessage,
    MessageScheme,
    UnansweredQuestion,
)
from app.models.enums import (
    GrievanceEventType,
    GrievanceStatus,
    MessageRole,
    MessageSource,
    ResolutionOutcome,
    Role,
    StaffScope,
    UnansweredStatus,
)
from app.models.geography import Department, District
from app.models.grievance import (
    Grievance,
    GrievanceCategory,
    GrievanceNote,
    GrievanceStatusHistory,
)
from app.models.scheme import Scheme
from app.models.staff_profile import StaffProfile
from app.models.user import User
from app.schemas.citizen import DistrictOut
from app.schemas.grievance import NamedOut
from app.schemas.staff import (
    ActivityOut,
    CitizenContactOut,
    ComparisonOut,
    CountOut,
    DailyOut,
    NoteIn,
    OverviewOut,
    PeriodPairOut,
    StaffEventOut,
    StaffGrievanceList,
    StaffGrievanceOut,
    StaffGrievanceRow,
    StaffMeOut,
    StaffNoteOut,
    StatusChangeIn,
    TotalsOut,
    TranscriptMessageOut,
    TrendDayOut,
    UnansweredOut,
)

STAFF_ROLES = frozenset({Role.officer.value, Role.admin.value, Role.superadmin.value})
OVERVIEW_ROLES = frozenset({Role.admin.value, Role.superadmin.value})

S = GrievanceStatus
OPEN_STATUSES = (S.new, S.assigned, S.under_verification, S.in_progress, S.reopened)
DONE_STATUSES = (S.resolved, S.closed)

# Allowed moves. "assigned" means "I'm taking this one".
_MOVES: dict[S, tuple[S, ...]] = {
    S.new: (S.assigned, S.under_verification, S.in_progress, S.closed),
    S.assigned: (S.under_verification, S.in_progress, S.closed),
    S.under_verification: (S.in_progress, S.resolved, S.closed),
    S.in_progress: (S.under_verification, S.resolved, S.closed),
    S.resolved: (S.closed, S.reopened),
    S.closed: (S.reopened,),
    S.reopened: (S.under_verification, S.in_progress, S.resolved, S.closed),
}
TRANSITIONS = {k.value: tuple(v.value for v in vs) for k, vs in _MOVES.items()}
# The citizen sees status remarks, and these moves need a reason.
REMARK_REQUIRED = frozenset({S.resolved.value, S.closed.value, S.reopened.value})


def next_statuses(status: str) -> list[str]:
    return list(TRANSITIONS.get(status, ()))


def _utc(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


def _who(user: User | None) -> str | None:
    """A display name for staff/citizens: name, else the last digits of the mobile."""
    if user is None:
        return None
    if user.name:
        return user.name
    if user.mobile:
        return f"••••{user.mobile[-4:]}"
    return user.email


# --- jurisdiction ----------------------------------------------------------------


async def _profile(db: AsyncSession, user: User) -> StaffProfile | None:
    return cast(
        "StaffProfile | None",
        await db.scalar(
            select(StaffProfile)
            .where(StaffProfile.user_id == user.id)
            .options(
                selectinload(StaffProfile.district),
                selectinload(StaffProfile.department),
            )
        ),
    )


class Scope:
    """The caller's jurisdiction, as SQL conditions on ``Grievance``."""

    def __init__(self, user: User, profile: StaffProfile | None) -> None:
        self.user = user
        self.profile = profile
        self.level = StaffScope.system.value
        self.district_id: uuid.UUID | None = None
        self.state_code: str | None = None
        self.grievance: list[ColumnElement[bool]] = []

        if user.role == Role.superadmin.value:
            return
        if user.role not in STAFF_ROLES:
            raise APIError(["authz.forbidden"], 403)
        if profile is None or not profile.is_active:
            raise APIError(["resource.staff.no_jurisdiction"], 403)

        self.level = profile.scope_level
        if self.level == StaffScope.state.value:
            self.state_code = profile.state_code
            self.grievance.append(
                Grievance.district_id.in_(
                    select(District.id).where(District.state_code == profile.state_code)
                )
            )
        elif self.level in (StaffScope.district.value, StaffScope.tehsil.value):
            if profile.district_id is None:
                raise APIError(["resource.staff.no_jurisdiction"], 403)
            self.district_id = profile.district_id
            self.grievance.append(Grievance.district_id == profile.district_id)
            if self.level == StaffScope.tehsil.value:
                if profile.tehsil_id is None:
                    raise APIError(["resource.staff.no_jurisdiction"], 403)
                self.grievance.append(Grievance.tehsil_id == profile.tehsil_id)
        elif self.level != StaffScope.system.value:
            raise APIError(["resource.staff.no_jurisdiction"], 403)

        if profile.department_id is not None:
            self.grievance.append(Grievance.department_id == profile.department_id)

    def citizens(self, stmt: Select[Any], user_id: Any) -> Select[Any]:
        """Narrow a citizen-activity query (chats, schemes) to the caller's geography,
        using the district on the citizen's profile."""
        if self.district_id is not None:
            return stmt.join(CitizenProfile, CitizenProfile.user_id == user_id).where(
                CitizenProfile.district_id == self.district_id
            )
        if self.state_code is not None:
            # Citizens who haven't picked a district yet still count state-wide.
            return (
                stmt.outerjoin(CitizenProfile, CitizenProfile.user_id == user_id)
                .outerjoin(District, District.id == CitizenProfile.district_id)
                .where(
                    or_(
                        CitizenProfile.district_id.is_(None),
                        District.state_code == self.state_code,
                    )
                )
            )
        return stmt


async def scope_for(db: AsyncSession, user: User) -> Scope:
    return Scope(user, await _profile(db, user))


async def me(db: AsyncSession, user: User) -> StaffMeOut:
    profile = await _profile(db, user)
    Scope(user, profile)  # refuses non-staff and staff without a jurisdiction
    return StaffMeOut(
        name=user.name,
        mobile=user.mobile,
        role=user.role,
        designation=profile.designation if profile else None,
        scope_level=profile.scope_level if profile else StaffScope.system.value,
        district=DistrictOut.model_validate(profile.district)
        if profile and profile.district
        else None,
        department=NamedOut.model_validate(profile.department)
        if profile and profile.department
        else None,
        can_view_overview=user.role in OVERVIEW_ROLES,
    )


# --- queue ---------------------------------------------------------------------------


def _row(g: Grievance, now: dt.datetime) -> StaffGrievanceRow:
    due = _utc(g.due_at)
    return StaffGrievanceRow(
        reference_no=g.reference_no,
        status=g.status,
        priority=g.priority,
        summary=g.summary,
        category=NamedOut.model_validate(g.category),
        district=DistrictOut.model_validate(g.district),
        department=NamedOut.model_validate(g.department) if g.department else None,
        citizen_name=_who(g.citizen),
        assigned_officer=_who(g.assigned_officer),
        submitted_at=cast("dt.datetime", _utc(g.submitted_at)),
        due_at=due,
        overdue=bool(due and due < now and g.status in {s.value for s in OPEN_STATUSES}),
        possible_duplicate=g.possible_duplicate_of_id is not None,
    )


async def list_queue(
    db: AsyncSession,
    user: User,
    *,
    status: str | None = None,
    district_code: str | None = None,
    department_code: str | None = None,
    query: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> StaffGrievanceList:
    scope = await scope_for(db, user)
    now = dt.datetime.now(dt.UTC)

    filters = list(scope.grievance)
    if district_code:
        filters.append(
            Grievance.district_id.in_(select(District.id).where(District.code == district_code))
        )
    if department_code:
        filters.append(
            Grievance.department_id.in_(
                select(Department.id).where(Department.code == department_code)
            )
        )
    if query and query.strip():
        needle = f"%{query.strip()}%"
        filters.append(or_(Grievance.reference_no.like(needle), Grievance.summary.like(needle)))

    count_rows = await db.execute(
        select(Grievance.status, func.count()).where(*filters).group_by(Grievance.status)
    )
    counts = {str(k): int(v) for k, v in count_rows.all()}
    overdue_count = int(
        await db.scalar(
            select(func.count())
            .select_from(Grievance)
            .where(
                *filters,
                Grievance.status.in_([s.value for s in OPEN_STATUSES]),
                Grievance.due_at < now,
            )
        )
        or 0
    )

    if status == "open":
        filters.append(Grievance.status.in_([s.value for s in OPEN_STATUSES]))
    elif status == "overdue":
        filters.append(Grievance.status.in_([s.value for s in OPEN_STATUSES]))
        filters.append(Grievance.due_at < now)
    elif status:
        filters.append(Grievance.status == status)

    total = cast(
        "int", await db.scalar(select(func.count()).select_from(Grievance).where(*filters))
    )
    rows = await db.scalars(
        select(Grievance)
        .where(*filters)
        .options(
            selectinload(Grievance.category),
            selectinload(Grievance.district),
            selectinload(Grievance.department),
            selectinload(Grievance.citizen),
            selectinload(Grievance.assigned_officer),
        )
        .order_by(Grievance.submitted_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return StaffGrievanceList(
        items=[_row(g, now) for g in rows],
        total=total,
        status_counts=counts,
        overdue_count=overdue_count,
    )


async def departments(db: AsyncSession, user: User) -> list[NamedOut]:
    """Departments grievances are routed to (for the queue filter). A staff member
    tied to one department only gets that one."""
    scope = await scope_for(db, user)
    stmt = (
        select(Department)
        .where(
            Department.id.in_(
                select(GrievanceCategory.department_id).where(
                    GrievanceCategory.department_id.is_not(None)
                )
            )
        )
        .order_by(Department.name_en)
    )
    if scope.profile is not None and scope.profile.department_id is not None:
        stmt = stmt.where(Department.id == scope.profile.department_id)
    return [NamedOut.model_validate(d) for d in await db.scalars(stmt)]


# --- one grievance -------------------------------------------------------------------------


async def _scoped(db: AsyncSession, scope: Scope, reference_no: str) -> Grievance:
    g = await db.scalar(
        select(Grievance)
        .where(Grievance.reference_no == reference_no, *scope.grievance)
        .options(
            selectinload(Grievance.category),
            selectinload(Grievance.subcategory),
            selectinload(Grievance.district),
            selectinload(Grievance.department),
            selectinload(Grievance.citizen),
            selectinload(Grievance.assigned_officer),
            selectinload(Grievance.possible_duplicate_of),
            selectinload(Grievance.history).selectinload(GrievanceStatusHistory.changed_by),
            selectinload(Grievance.notes).selectinload(GrievanceNote.author),
        )
        .execution_options(populate_existing=True)
    )
    if g is None:
        raise APIError(["resource.grievance.not_found"], 404)
    return g


async def get_grievance(db: AsyncSession, user: User, reference_no: str) -> StaffGrievanceOut:
    scope = await scope_for(db, user)
    g = await _scoped(db, scope, reference_no)
    now = dt.datetime.now(dt.UTC)

    transcript: list[TranscriptMessageOut] = []
    if g.conversation_id is not None:
        messages = await db.scalars(
            select(ConversationMessage)
            .where(
                ConversationMessage.conversation_id == g.conversation_id,
                ConversationMessage.role.in_(
                    [MessageRole.citizen.value, MessageRole.assistant.value]
                ),
            )
            .order_by(ConversationMessage.created_at)
        )
        transcript = [
            TranscriptMessageOut(
                role=m.role,
                content=m.content,
                source=m.source,
                original_transcript=m.original_transcript if m.transcript_corrected else None,
                transcript_corrected=m.transcript_corrected,
                created_at=cast("dt.datetime", _utc(m.created_at)),
            )
            for m in messages
        ]

    officer_ids = {h.to_officer_id for h in g.history if h.to_officer_id}
    officers = (
        {u.id: u for u in await db.scalars(select(User).where(User.id.in_(officer_ids)))}
        if officer_ids
        else {}
    )

    log_activity(
        topic="grievance",
        action="staff.view",
        result="succeed",
        category="user",
        user_id=user.id,
        actor_role=user.role,
        target_type="grievance",
        target_id=g.reference_no,
    )
    return StaffGrievanceOut(
        **_row(g, now).model_dump(),
        subcategory=NamedOut.model_validate(g.subcategory) if g.subcategory else None,
        location_detail=g.location_detail,
        description=g.description,
        since=(g.extra_fields or {}).get("since"),
        prior_complaint=g.prior_complaint,
        language=g.language,
        possible_duplicate_of=g.possible_duplicate_of.reference_no
        if g.possible_duplicate_of
        else None,
        resolution_outcome=g.resolution_outcome,
        resolution_note=g.resolution_note,
        citizen=CitizenContactOut(
            name=g.citizen.name,
            mobile=g.citizen.mobile,
            preferred_language=g.citizen.preferred_language,
        ),
        transcript=transcript,
        history=[
            StaffEventOut(
                event_type=h.event_type,
                from_status=h.from_status,
                to_status=h.to_status,
                to_officer=_who(officers.get(h.to_officer_id)) if h.to_officer_id else None,
                changed_by=_who(h.changed_by),
                remark=h.remark,
                created_at=cast("dt.datetime", _utc(h.created_at)),
            )
            for h in g.history
        ],
        notes=[
            StaffNoteOut(
                content=n.content,
                visibility=n.visibility,
                author=_who(n.author),
                created_at=cast("dt.datetime", _utc(n.created_at)),
            )
            for n in g.notes
        ],
        next_statuses=next_statuses(g.status),
    )


async def change_status(
    db: AsyncSession, user: User, reference_no: str, payload: StatusChangeIn
) -> StaffGrievanceOut:
    scope = await scope_for(db, user)
    g = await _scoped(db, scope, reference_no)
    target = payload.status
    if target not in next_statuses(g.status):
        raise APIError(["resource.grievance.invalid_transition"], 422)
    remark = (payload.remark or "").strip() or None
    if target in REMARK_REQUIRED and remark is None:
        raise APIError(["resource.grievance.remark_required"], 422)
    outcome = payload.resolution_outcome or None
    if outcome is not None and outcome not in {o.value for o in ResolutionOutcome}:
        raise APIError(["resource.grievance.invalid_outcome"], 422)

    now = dt.datetime.now(dt.UTC)
    before = g.status
    # The officer who first acts on an unassigned grievance takes it.
    if g.assigned_officer_id is None and user.role == Role.officer.value:
        g.assigned_officer_id = user.id
        db.add(
            GrievanceStatusHistory(
                grievance_id=g.id,
                event_type=GrievanceEventType.assignment.value,
                to_officer_id=user.id,
                changed_by_id=user.id,
                created_at=now,
            )
        )
    g.status = target
    if target == S.resolved.value:
        g.resolved_at = now
        g.resolution_note = remark
        g.resolution_outcome = outcome or ResolutionOutcome.resolved_fully.value
    elif target == S.closed.value:
        g.closed_at = now
        if outcome:
            g.resolution_outcome = outcome
        if g.resolution_note is None:
            g.resolution_note = remark
    elif target == S.reopened.value:
        g.reopen_count += 1
        g.resolved_at = None
        g.closed_at = None
    db.add(
        GrievanceStatusHistory(
            grievance_id=g.id,
            event_type=GrievanceEventType.status_change.value,
            from_status=before,
            to_status=target,
            changed_by_id=user.id,
            remark=remark,
            # A tick later than the assignment entry, so the timeline keeps its order.
            created_at=now + dt.timedelta(microseconds=1),
        )
    )
    await db.commit()

    log_activity(
        topic="grievance",
        action="staff.status",
        result="succeed",
        category="user",
        user_id=user.id,
        actor_role=user.role,
        target_type="grievance",
        target_id=g.reference_no,
        before={"status": before},
        after={"status": target, "resolution_outcome": g.resolution_outcome},
    )
    return await get_grievance(db, user, reference_no)


async def add_note(
    db: AsyncSession, user: User, reference_no: str, payload: NoteIn
) -> StaffGrievanceOut:
    scope = await scope_for(db, user)
    g = await _scoped(db, scope, reference_no)
    db.add(
        GrievanceNote(
            grievance_id=g.id,
            author_id=user.id,
            visibility=payload.visibility,
            content=payload.content.strip(),
        )
    )
    await db.commit()
    log_activity(
        topic="grievance",
        action="staff.note",
        result="succeed",
        category="user",
        user_id=user.id,
        actor_role=user.role,
        target_type="grievance",
        target_id=g.reference_no,
        after={"visibility": payload.visibility},  # never the note text
    )
    return await get_grievance(db, user, reference_no)


# --- administrator overview ------------------------------------------------------------------


def _counts(rows: Any) -> list[CountOut]:
    return [
        CountOut(code=code, name_en=name_en, name_pa=name_pa, count=int(n))
        for code, name_en, name_pa, n in rows
    ]


async def _period_figures(
    db: AsyncSession, in_scope: list[ColumnElement[bool]], *, now: dt.datetime, days: int
) -> tuple[ComparisonOut, list[TrendDayOut]]:
    """This period vs the one before it, and a day-by-day trend for this period.

    A grievance counts as done (resolved) when it was resolved or closed; it became
    overdue on its due date if it was still not done by then."""
    since = now - dt.timedelta(days=days)
    before = since - dt.timedelta(days=days)
    done_at = func.coalesce(Grievance.resolved_at, Grievance.closed_at)
    rows = (
        await db.execute(
            select(Grievance.submitted_at, done_at, Grievance.due_at).where(
                *in_scope,
                or_(
                    Grievance.submitted_at >= before,
                    done_at >= before,
                    Grievance.due_at >= before,
                ),
            )
        )
    ).all()

    first = now.date() - dt.timedelta(days=days - 1)
    trend = {first + dt.timedelta(days=i): [0, 0, 0] for i in range(days)}
    registered = [0, 0]
    resolved = [0, 0]
    overdue = [0, 0]
    durations: tuple[list[float], list[float]] = ([], [])

    def bucket(at: dt.datetime) -> int | None:
        if at >= since:
            return 0
        if at >= before:
            return 1
        return None

    for submitted, done, due in rows:
        submitted, done, due = _utc(submitted), _utc(done), _utc(due)
        if submitted and (b := bucket(submitted)) is not None:
            registered[b] += 1
            if b == 0 and submitted.date() in trend:
                trend[submitted.date()][0] += 1
        # No "done <= now" check: MySQL rounds to the second, so a grievance closed a
        # moment ago can look a fraction of a second in the future.
        if done and (b := bucket(done)) is not None:
            resolved[b] += 1
            if submitted:
                durations[b].append((done - submitted).total_seconds() / 86400)
            if b == 0 and done.date() in trend:
                trend[done.date()][1] += 1
        if due and due <= now and (done is None or done > due) and (b := bucket(due)) is not None:
            overdue[b] += 1
            if b == 0 and due.date() in trend:
                trend[due.date()][2] += 1

    def avg(values: list[float]) -> float:
        return round(sum(values) / len(values), 1) if values else 0.0

    def pair(values: list[int] | tuple[float, float]) -> PeriodPairOut:
        return PeriodPairOut(current=values[0], previous=values[1])

    comparison = ComparisonOut(
        registered=pair(registered),
        resolved=pair(resolved),
        overdue=pair(overdue),
        avg_resolution_days=pair((avg(durations[0]), avg(durations[1]))),
    )
    return comparison, [
        TrendDayOut(date=day, new=n, resolved=r, overdue=o) for day, (n, r, o) in trend.items()
    ]


async def overview(
    db: AsyncSession,
    user: User,
    *,
    days: int = 30,
    district_code: str | None = None,
    department_code: str | None = None,
) -> OverviewOut:
    if user.role not in OVERVIEW_ROLES:
        raise APIError(["authz.forbidden"], 403)
    scope = await scope_for(db, user)
    now = dt.datetime.now(dt.UTC)
    since = now - dt.timedelta(days=days)
    in_scope = list(scope.grievance)
    # Optional narrowing within the caller's jurisdiction (never wider than it).
    if district_code:
        in_scope.append(
            Grievance.district_id.in_(select(District.id).where(District.code == district_code))
        )
    if department_code:
        in_scope.append(
            Grievance.department_id.in_(
                select(Department.id).where(Department.code == department_code)
            )
        )
    open_values = [s.value for s in OPEN_STATUSES]

    by_status = {
        str(k): int(v)
        for k, v in (
            await db.execute(
                select(Grievance.status, func.count()).where(*in_scope).group_by(Grievance.status)
            )
        ).all()
    }
    total = sum(by_status.values())

    async def count(stmt: Select[Any]) -> int:
        return int(await db.scalar(stmt) or 0)

    overdue = await count(
        select(func.count())
        .select_from(Grievance)
        .where(*in_scope, Grievance.status.in_(open_values), Grievance.due_at < now)
    )
    new_in_period = await count(
        select(func.count())
        .select_from(Grievance)
        .where(*in_scope, Grievance.submitted_at >= since)
    )

    by_category = _counts(
        (
            await db.execute(
                select(
                    GrievanceCategory.code,
                    GrievanceCategory.name_en,
                    GrievanceCategory.name_pa,
                    func.count(Grievance.id),
                )
                .join(Grievance, Grievance.category_id == GrievanceCategory.id)
                .where(*in_scope)
                .group_by(GrievanceCategory.id)
                .order_by(func.count(Grievance.id).desc())
            )
        ).all()
    )
    by_district = _counts(
        (
            await db.execute(
                select(District.code, District.name_en, District.name_pa, func.count(Grievance.id))
                .join(Grievance, Grievance.district_id == District.id)
                .where(*in_scope)
                .group_by(District.id)
                .order_by(func.count(Grievance.id).desc())
            )
        ).all()
    )

    # Citizen activity, narrowed to the caller's geography via the citizen's district.
    asked = func.count(func.distinct(ConversationMessage.conversation_id))
    scheme_stmt = (
        select(Scheme.slug, Scheme.name, Scheme.name_pa, asked)
        .join(MessageScheme, MessageScheme.scheme_id == Scheme.id)
        .join(ConversationMessage, ConversationMessage.id == MessageScheme.message_id)
        .join(Conversation, Conversation.id == ConversationMessage.conversation_id)
        .where(MessageScheme.created_at >= since)
        .group_by(Scheme.id)
        .order_by(asked.desc())
        .limit(10)
    )
    top_schemes = _counts(
        (await db.execute(scope.citizens(scheme_stmt, Conversation.user_id))).all()
    )

    citizens = await count(
        scope.citizens(
            select(func.count()).select_from(User).where(User.role == Role.citizen.value), User.id
        )
    )
    conversations = await count(
        scope.citizens(
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.started_at >= since, Conversation.turn_count > 0),
            Conversation.user_id,
        )
    )
    citizen_msgs = scope.citizens(
        select(ConversationMessage.source, func.count())
        .join(Conversation, Conversation.id == ConversationMessage.conversation_id)
        .where(
            ConversationMessage.role == MessageRole.citizen.value,
            ConversationMessage.created_at >= since,
        )
        .group_by(ConversationMessage.source),
        Conversation.user_id,
    )
    by_source = {str(k): int(v) for k, v in (await db.execute(citizen_msgs)).all()}
    spoken = by_source.get(MessageSource.voice.value, 0)
    voice_share = spoken / sum(by_source.values()) if by_source else 0.0

    unanswered_filter: list[ColumnElement[bool]] = [
        UnansweredQuestion.status == UnansweredStatus.open.value
    ]
    if scope.district_id is not None:
        unanswered_filter.append(UnansweredQuestion.district_id == scope.district_id)
    unanswered_open = await count(
        select(func.count()).select_from(UnansweredQuestion).where(*unanswered_filter)
    )
    unanswered = [
        UnansweredOut(
            question=q.question,
            language=q.language,
            created_at=cast("dt.datetime", _utc(q.created_at)),
        )
        for q in await db.scalars(
            select(UnansweredQuestion)
            .where(*unanswered_filter)
            .order_by(UnansweredQuestion.created_at.desc())
            .limit(5)
        )
    ]

    # Last 14 days, one row per day (zero-filled).
    trend_days = 14
    start = (now - dt.timedelta(days=trend_days - 1)).date()
    start_at = dt.datetime.combine(start, dt.time(), tzinfo=dt.UTC)
    g_day = func.date(Grievance.submitted_at)
    grievance_days = {
        str(d): int(n)
        for d, n in (
            await db.execute(
                select(g_day, func.count())
                .where(*in_scope, Grievance.submitted_at >= start_at)
                .group_by(g_day)
            )
        ).all()
    }
    c_day = func.date(Conversation.started_at)
    conversation_days = {
        str(d): int(n)
        for d, n in (
            await db.execute(
                scope.citizens(
                    select(c_day, func.count())
                    .where(Conversation.started_at >= start_at, Conversation.turn_count > 0)
                    .group_by(c_day),
                    Conversation.user_id,
                )
            )
        ).all()
    }
    daily = []
    for i in range(trend_days):
        day = start + dt.timedelta(days=i)
        daily.append(
            DailyOut(
                date=day,
                grievances=grievance_days.get(day.isoformat(), 0),
                conversations=conversation_days.get(day.isoformat(), 0),
            )
        )

    events = (
        await db.execute(
            select(GrievanceStatusHistory, Grievance.reference_no)
            .join(Grievance, Grievance.id == GrievanceStatusHistory.grievance_id)
            .where(*in_scope)
            .options(selectinload(GrievanceStatusHistory.changed_by))
            .order_by(GrievanceStatusHistory.created_at.desc())
            .limit(8)
        )
    ).all()
    recent_activity = [
        ActivityOut(
            reference_no=ref,
            event_type=h.event_type,
            to_status=h.to_status,
            changed_by=_who(h.changed_by),
            created_at=cast("dt.datetime", _utc(h.created_at)),
        )
        for h, ref in events
    ]

    comparison, trend = await _period_figures(db, in_scope, now=now, days=days)
    by_department = _counts(
        (
            await db.execute(
                select(Department.code, Department.name_en, Department.name_pa, func.count())
                .join(Grievance, Grievance.department_id == Department.id)
                .where(*in_scope)
                .group_by(Department.id)
                .order_by(func.count().desc())
            )
        ).all()
    )
    by_priority = {
        str(k): int(v)
        for k, v in (
            await db.execute(
                select(Grievance.priority, func.count())
                .where(*in_scope)
                .group_by(Grievance.priority)
            )
        ).all()
    }

    return OverviewOut(
        days=days,
        comparison=comparison,
        trend=trend,
        by_department=by_department,
        by_priority=by_priority,
        totals=TotalsOut(
            grievances=total,
            open=sum(by_status.get(s, 0) for s in open_values),
            resolved=sum(by_status.get(s.value, 0) for s in DONE_STATUSES),
            overdue=overdue,
            new_in_period=new_in_period,
            citizens=citizens,
            conversations_in_period=conversations,
            voice_share=round(voice_share, 3),
            unanswered_open=unanswered_open,
        ),
        by_status=by_status,
        by_category=by_category,
        by_district=by_district,
        top_schemes=top_schemes,
        daily=daily,
        unanswered=unanswered,
        recent_activity=recent_activity,
    )
