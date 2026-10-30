"""Citizen-side grievance schemas (spec §5.8)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.citizen import DistrictOut


class NamedOut(BaseModel):
    """Anything with a code and English/Punjabi names (category, department)."""

    model_config = ConfigDict(from_attributes=True)

    code: str
    name_en: str
    name_pa: str | None


class CategoryOut(NamedOut):
    department: NamedOut | None
    subcategories: list[NamedOut] = []


class GrievanceDraftOut(BaseModel):
    """What the assistant gathered, pre-filled into the review screen."""

    conversation_id: uuid.UUID | None
    category_code: str | None
    subcategory_code: str | None
    district_code: str | None
    location_detail: str | None
    summary: str | None
    description: str | None
    since: str | None
    prior_complaint: str | None


class GrievanceIn(BaseModel):
    conversation_id: uuid.UUID | None = None
    category_code: str = Field(max_length=50)
    subcategory_code: str | None = Field(default=None, max_length=50)
    district_code: str = Field(max_length=10)
    location_detail: str | None = Field(default=None, max_length=255)
    summary: str | None = Field(default=None, max_length=255)
    description: str = Field(min_length=10, max_length=4000)
    since: str | None = Field(default=None, max_length=120)
    prior_complaint: str | None = Field(default=None, max_length=1000)


class StatusEventOut(BaseModel):
    to_status: str | None
    remark: str | None
    created_at: datetime


class CitizenUpdateOut(BaseModel):
    """An officer's citizen-visible note (internal notes are never returned)."""

    content: str
    created_at: datetime


class GrievanceSummaryOut(BaseModel):
    reference_no: str
    status: str
    summary: str
    category: NamedOut
    district: DistrictOut
    submitted_at: datetime
    due_at: datetime | None


class GrievanceOut(GrievanceSummaryOut):
    subcategory: NamedOut | None
    department: NamedOut | None
    location_detail: str | None
    description: str
    since: str | None
    prior_complaint: str | None
    language: str
    possible_duplicate_of: str | None  # reference number of the earlier grievance
    history: list[StatusEventOut]
    updates: list[CitizenUpdateOut]
