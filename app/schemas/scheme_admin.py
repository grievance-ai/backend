"""Administrator view of the scheme knowledge base."""

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.grievance import NamedOut
from app.schemas.staff import UnansweredOut


class SchemeTotalsOut(BaseModel):
    total: int  # every scheme, active or not
    active: int
    verified: int  # active and checked by a person against the source
    needs_review: int  # active, not checked yet (or changed since)
    unanswered_open: int  # questions the assistant could not answer, not yet reviewed


class SchemeRowOut(BaseModel):
    slug: str
    name: str
    short_name: str | None
    name_pa: str | None
    level: str  # central | state
    department: NamedOut | None
    is_active: bool
    review_status: str  # verified | needs_review
    last_verified_on: dt.date | None
    source_name: str | None
    source_url: str | None
    official_url: str | None
    times_suggested: int  # conversations whose answers named this scheme (in scope)
    updated_at: dt.datetime


class SchemeListOut(BaseModel):
    totals: SchemeTotalsOut
    items: list[SchemeRowOut]
    unanswered: list[UnansweredOut]  # latest open ones
    can_review: bool  # state / system administrators


class SchemeConditionOut(BaseModel):
    field: str
    operator: str
    value: Any
    description: str
    any_of_group: str | None


class SchemeDetailOut(SchemeRowOut):
    administering_body: str | None
    description: str
    benefits: str
    required_documents: list[str]
    application_steps: list[str]
    application_mode: str | None
    deadline_info: str | None
    contact: str | None
    category_tags: list[str]
    keywords: list[str]
    conditions: list[SchemeConditionOut]
    has_search_vector: bool  # embedded for the current search model
    reviewed_by: str | None  # who last changed the review status here
    can_review: bool


class SchemeReviewIn(BaseModel):
    review_status: Literal["verified", "needs_review"]
    note: str | None = Field(default=None, max_length=500)
