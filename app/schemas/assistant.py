"""Request/response schemas for the citizen assistant (conversations)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Lang = Literal["en", "pa"]
Eligibility = Literal["yes", "no", "unknown"]
ConditionStatus = Literal["met", "not_met", "unknown"]


class ChatMessageIn(BaseModel):
    conversation_id: uuid.UUID | None = None  # omit to start a new conversation
    text: str = Field(min_length=1, max_length=2000)
    language: Lang = "pa"
    # From POST /conversations/transcriptions when the text started as a voice clip.
    voice_token: str | None = Field(default=None, max_length=8192)


class TranscriptionOut(BaseModel):
    """Speech-to-text result. Show ``text`` for the citizen to check and edit, then
    send it with ``voice_token`` so the original transcript is kept."""

    text: str
    language: str | None  # as heard ("pa" / "en"), when known
    voice_token: str


class ConditionOut(BaseModel):
    text: str
    status: ConditionStatus


class SchemeCardOut(BaseModel):
    """A grounded scheme answer: official name/link from the database, the
    explanation (in the citizen's language) from the assistant."""

    slug: str
    name: str
    short_name: str | None
    name_pa: str | None
    eligible: Eligibility
    summary: str
    benefit: str
    conditions: list[ConditionOut]
    documents: list[str]
    steps: list[str]
    official_url: str | None
    contact: str | None


class WebSourceOut(BaseModel):
    url: str  # an official government page (allowlisted domain)
    title: str  # its site name / domain


class OfficialWebOut(BaseModel):
    """An answer found on official government websites, not yet verified by us."""

    found: bool
    sources: list[WebSourceOut] = []


class MessageOut(BaseModel):
    id: uuid.UUID
    role: Literal["citizen", "assistant"]
    content: str
    language: str | None
    created_at: datetime
    source: Literal["typed", "voice"] = "typed"
    answer_status: str | None = None
    schemes: list[SchemeCardOut] = []
    follow_ups: list[str] = []
    # The assistant has a complete grievance draft: show "Review & register".
    grievance_ready: bool = False
    # "pending": the scheme is not in our list and the app should now call
    # POST /conversations/messages/{id}/official-search (showing a "checking
    # official websites" animation). "done": that search has run.
    official_search: Literal["pending", "done"] | None = None
    # Set on the message that carries an official-website answer.
    web: OfficialWebOut | None = None


class ChatTurnOut(BaseModel):
    conversation_id: uuid.UUID
    mode: str
    user_message: MessageOut
    assistant_message: MessageOut


class ConversationSummaryOut(BaseModel):
    id: uuid.UUID
    mode: str
    language: str
    title: str | None
    started_at: datetime
    last_message_at: datetime | None


class ConversationOut(ConversationSummaryOut):
    messages: list[MessageOut]
