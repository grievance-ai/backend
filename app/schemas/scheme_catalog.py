"""The scheme catalogue citizens browse (the same data the assistant answers from)."""

import datetime as dt

from pydantic import BaseModel

from app.schemas.grievance import NamedOut


class SchemeSummaryOut(BaseModel):
    slug: str
    name: str
    short_name: str | None
    name_pa: str | None
    level: str  # central | state
    department: NamedOut | None
    description: str  # English: the scheme data is stored in English
    benefits: str
    category_tags: list[str]
    official_url: str | None


class SchemeInfoOut(SchemeSummaryOut):
    administering_body: str | None
    conditions: list[str]  # "who can get it", one line each
    any_of_conditions: list[list[str]]  # groups where meeting one is enough
    required_documents: list[str]
    application_steps: list[str]
    application_mode: str | None
    deadline_info: str | None
    contact: str | None
    source_name: str | None
    source_url: str | None
    checked_on: dt.date | None  # when a person last checked it against the source
