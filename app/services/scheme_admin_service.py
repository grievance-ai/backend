"""Administrator view of the scheme knowledge base: what the assistant answers from,
where each scheme came from, and whether a person has checked it.

- Administrators (any scope) and superadmins can view. Usage counts and
  unanswered questions are narrowed to the caller's geography, like the overview.
- Only state- or system-level administrators and superadmins can change a
  scheme's review status: schemes are shared by every district.
"""

import datetime as dt
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.activity import log_activity
from app.core.errors import APIError
from app.integrations import embeddings
from app.models.conversation import (
    Conversation,
    ConversationMessage,
    MessageScheme,
    UnansweredQuestion,
)
from app.models.enums import Role, SchemeReviewStatus, StaffScope, UnansweredStatus
from app.models.scheme import Scheme, SchemeEmbedding
from app.models.user import User
from app.schemas.grievance import NamedOut
from app.schemas.scheme_admin import (
    SchemeConditionOut,
    SchemeDetailOut,
    SchemeListOut,
    SchemeReviewIn,
    SchemeRowOut,
    SchemeTotalsOut,
)
from app.schemas.staff import UnansweredOut
from app.services.staff_service import OVERVIEW_ROLES, Scope, scope_for

UNANSWERED_SHOWN = 10


async def _admin_scope(db: AsyncSession, user: User) -> Scope:
    if user.role not in OVERVIEW_ROLES:
        raise APIError(["authz.forbidden"], 403)
    return await scope_for(db, user)


def _can_review(user: User, scope: Scope) -> bool:
    return user.role == Role.superadmin.value or scope.level in (
        StaffScope.state.value,
        StaffScope.system.value,
    )


def _utc(value: dt.datetime) -> dt.datetime:
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


async def _times_suggested(db: AsyncSession, scope: Scope) -> dict[Any, int]:
    """Conversations, per scheme, whose answers named it (in the caller's geography)."""
    stmt = (
        select(MessageScheme.scheme_id, func.count(func.distinct(Conversation.id)))
        .join(ConversationMessage, ConversationMessage.id == MessageScheme.message_id)
        .join(Conversation, Conversation.id == ConversationMessage.conversation_id)
        .group_by(MessageScheme.scheme_id)
    )
    rows = (await db.execute(scope.citizens(stmt, Conversation.user_id))).all()
    return {scheme_id: int(n) for scheme_id, n in rows}


def _row(s: Scheme, suggested: int) -> dict[str, Any]:
    return {
        "slug": s.slug,
        "name": s.name,
        "short_name": s.short_name,
        "name_pa": s.name_pa,
        "level": s.level,
        "department": NamedOut.model_validate(s.department) if s.department else None,
        "is_active": s.is_active,
        "review_status": s.review_status,
        "last_verified_on": s.last_verified_on,
        "source_name": s.source_name,
        "source_url": s.source_url,
        "official_url": s.official_url,
        "times_suggested": suggested,
        "updated_at": _utc(s.updated_at),
    }


async def list_schemes(db: AsyncSession, user: User) -> SchemeListOut:
    scope = await _admin_scope(db, user)
    schemes = list(
        (
            await db.scalars(
                select(Scheme).options(selectinload(Scheme.department)).order_by(Scheme.name)
            )
        ).all()
    )
    suggested = await _times_suggested(db, scope)

    unanswered_filter: list[ColumnElement[bool]] = [
        UnansweredQuestion.status == UnansweredStatus.open.value
    ]
    if scope.district_id is not None:
        unanswered_filter.append(UnansweredQuestion.district_id == scope.district_id)
    unanswered_open = int(
        await db.scalar(
            select(func.count()).select_from(UnansweredQuestion).where(*unanswered_filter)
        )
        or 0
    )
    unanswered = [
        UnansweredOut(question=q.question, language=q.language, created_at=_utc(q.created_at))
        for q in await db.scalars(
            select(UnansweredQuestion)
            .where(*unanswered_filter)
            .order_by(UnansweredQuestion.created_at.desc())
            .limit(UNANSWERED_SHOWN)
        )
    ]

    active = [s for s in schemes if s.is_active]
    verified = sum(1 for s in active if s.review_status == SchemeReviewStatus.verified.value)
    return SchemeListOut(
        totals=SchemeTotalsOut(
            total=len(schemes),
            active=len(active),
            verified=verified,
            needs_review=len(active) - verified,
            unanswered_open=unanswered_open,
        ),
        items=[SchemeRowOut(**_row(s, suggested.get(s.id, 0))) for s in schemes],
        unanswered=unanswered,
        can_review=_can_review(user, scope),
    )


async def _get(db: AsyncSession, slug: str) -> Scheme:
    scheme = await db.scalar(
        select(Scheme)
        .where(Scheme.slug == slug)
        .options(selectinload(Scheme.department), selectinload(Scheme.conditions))
    )
    if scheme is None:
        raise APIError(["resource.scheme.not_found"], 404)
    return scheme


async def _detail(db: AsyncSession, user: User, scope: Scope, scheme: Scheme) -> SchemeDetailOut:
    suggested = await _times_suggested(db, scope)
    has_vector = (
        await db.scalar(
            select(func.count())
            .select_from(SchemeEmbedding)
            .where(
                SchemeEmbedding.scheme_id == scheme.id,
                SchemeEmbedding.model == embeddings.get_provider().model,
            )
        )
        or 0
    ) > 0
    reviewer = await db.get(User, scheme.updated_by_id) if scheme.updated_by_id else None
    return SchemeDetailOut(
        **_row(scheme, suggested.get(scheme.id, 0)),
        administering_body=scheme.administering_body,
        description=scheme.description,
        benefits=scheme.benefits,
        required_documents=list(scheme.required_documents or []),
        application_steps=list(scheme.application_steps or []),
        application_mode=scheme.application_mode,
        deadline_info=scheme.deadline_info,
        contact=scheme.contact,
        category_tags=[str(t) for t in scheme.category_tags or []],
        keywords=[str(k) for k in scheme.keywords or []],
        conditions=[
            SchemeConditionOut(
                field=c.field_name,
                operator=c.operator,
                value=c.value,
                description=c.description,
                any_of_group=c.group_key,
            )
            for c in scheme.conditions
        ],
        has_search_vector=has_vector,
        reviewed_by=(reviewer.name or reviewer.mobile) if reviewer else None,
        can_review=_can_review(user, scope),
    )


async def get_scheme(db: AsyncSession, user: User, slug: str) -> SchemeDetailOut:
    scope = await _admin_scope(db, user)
    return await _detail(db, user, scope, await _get(db, slug))


async def set_review(
    db: AsyncSession, user: User, slug: str, payload: SchemeReviewIn
) -> SchemeDetailOut:
    """Mark a scheme as checked against its source (or back to needs review)."""
    scope = await _admin_scope(db, user)
    if not _can_review(user, scope):
        raise APIError(["resource.scheme.review_forbidden"], 403)
    scheme = await _get(db, slug)
    before = {"review_status": scheme.review_status, "last_verified_on": scheme.last_verified_on}

    scheme.review_status = payload.review_status
    if payload.review_status == SchemeReviewStatus.verified.value:
        scheme.last_verified_on = dt.date.today()
    scheme.updated_by_id = user.id
    await db.commit()

    log_activity(
        topic="scheme",
        action="scheme.review",
        result="succeed",
        category="user",
        user_id=user.id,
        actor_role=user.role,
        target_type="scheme",
        target_id=scheme.slug,
        before={k: str(v) if v else None for k, v in before.items()},
        after={
            "review_status": scheme.review_status,
            "last_verified_on": str(scheme.last_verified_on) if scheme.last_verified_on else None,
            **({"note": payload.note} if payload.note else {}),
        },
    )
    return await _detail(db, user, scope, await _get(db, slug))
