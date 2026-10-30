"""Officer and administrator schemas (spec §5.9, §5.10)."""

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.citizen import DistrictOut
from app.schemas.grievance import NamedOut


class StaffMeOut(BaseModel):
    """Who the staff member is and what they can see."""

    name: str | None
    mobile: str | None
    role: str
    designation: str | None
    scope_level: str  # tehsil | district | state | system
    district: DistrictOut | None
    department: NamedOut | None
    can_view_overview: bool  # administrators only


class StaffGrievanceRow(BaseModel):
    reference_no: str
    status: str
    priority: str
    summary: str
    category: NamedOut
    district: DistrictOut
    department: NamedOut | None
    citizen_name: str | None
    assigned_officer: str | None
    submitted_at: dt.datetime
    due_at: dt.datetime | None
    overdue: bool
    possible_duplicate: bool


class StaffGrievanceList(BaseModel):
    items: list[StaffGrievanceRow]
    total: int  # matching the filters
    status_counts: dict[str, int]  # whole jurisdiction, ignoring the status filter


class CitizenContactOut(BaseModel):
    name: str | None
    mobile: str | None
    preferred_language: str


class TranscriptMessageOut(BaseModel):
    role: str  # citizen | assistant
    content: str
    source: str  # typed | voice
    original_transcript: str | None  # raw speech-to-text, when the citizen corrected it
    transcript_corrected: bool
    created_at: dt.datetime


class StaffEventOut(BaseModel):
    event_type: str  # status_change | assignment
    from_status: str | None
    to_status: str | None
    to_officer: str | None
    changed_by: str | None
    remark: str | None
    created_at: dt.datetime


class StaffNoteOut(BaseModel):
    content: str
    visibility: str  # internal | citizen
    author: str | None
    created_at: dt.datetime


class StaffGrievanceOut(StaffGrievanceRow):
    subcategory: NamedOut | None
    location_detail: str | None
    description: str
    since: str | None
    prior_complaint: str | None
    language: str
    possible_duplicate_of: str | None
    resolution_outcome: str | None
    resolution_note: str | None
    citizen: CitizenContactOut
    transcript: list[TranscriptMessageOut]
    history: list[StaffEventOut]
    notes: list[StaffNoteOut]
    next_statuses: list[str]  # the moves allowed from the current status


class StatusChangeIn(BaseModel):
    status: str = Field(max_length=25)
    remark: str | None = Field(default=None, max_length=2000)
    resolution_outcome: str | None = Field(default=None, max_length=30)


class NoteIn(BaseModel):
    content: str = Field(min_length=2, max_length=2000)
    visibility: Literal["internal", "citizen"] = "internal"


# --- administrator overview ------------------------------------------------------


class CountOut(BaseModel):
    code: str
    name_en: str
    name_pa: str | None
    count: int


class DailyOut(BaseModel):
    date: dt.date
    grievances: int
    conversations: int


class TotalsOut(BaseModel):
    grievances: int  # all time, in scope
    open: int
    resolved: int  # resolved or closed
    overdue: int  # open and past the due date
    new_in_period: int
    citizens: int
    conversations_in_period: int
    voice_share: float  # 0..1, citizen messages spoken rather than typed, in period
    unanswered_open: int


class UnansweredOut(BaseModel):
    question: str
    language: str | None
    created_at: dt.datetime


class ActivityOut(BaseModel):
    reference_no: str
    event_type: str
    to_status: str | None
    changed_by: str | None
    created_at: dt.datetime


class OverviewOut(BaseModel):
    days: int
    totals: TotalsOut
    by_status: dict[str, int]
    by_category: list[CountOut]
    by_district: list[CountOut]
    top_schemes: list[CountOut]  # conversations that discussed each scheme, in period
    daily: list[DailyOut]
    unanswered: list[UnansweredOut]
    recent_activity: list[ActivityOut]
