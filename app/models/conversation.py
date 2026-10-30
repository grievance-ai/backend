"""Conversations between a citizen and the assistant.

A conversation is one chat session. Its ``mode`` is (re)classified as the
citizen talks and can switch mid-way (scheme enquiry → grievance intake).
Messages are append-only; the transcript is what officers read on a grievance.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import GUID, Base, TimestampMixin
from app.models.enums import (
    ConversationMode,
    ConversationStatus,
    Language,
    MessageSource,
    UnansweredStatus,
)

PRECISE_DATETIME = DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql")

if TYPE_CHECKING:
    from app.models.scheme import Scheme
    from app.models.user import User


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    mode: Mapped[str] = mapped_column(
        String(20), default=ConversationMode.unclear.value, index=True
    )
    language: Mapped[str] = mapped_column(String(5), default=Language.pa.value)
    status: Mapped[str] = mapped_column(String(20), default=ConversationStatus.active.value)
    title: Mapped[str | None] = mapped_column(String(255), default=None)  # for history list
    turn_count: Mapped[int] = mapped_column(Integer, default=0)  # citizen messages
    # Facts gathered this session (so the assistant never asks twice), e.g. {"crop": "wheat"}
    context: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    # Grievance fields extracted so far, before the citizen confirms and submits
    grievance_draft: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    user: Mapped["User"] = relationship()
    messages: Mapped[list["ConversationMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ConversationMessage.created_at",
    )

    __table_args__ = (Index("ix_conversations_started_at", "started_at"),)


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("conversations.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(10))  # MessageRole
    content: Mapped[str] = mapped_column(Text)  # corrected text for voice; what everyone sees
    # Structured assistant answer (scheme cards, follow-ups) as shown to the citizen
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    language: Mapped[str | None] = mapped_column(String(5), default=None)

    # Voice input (citizen messages only)
    source: Mapped[str] = mapped_column(String(10), default=MessageSource.typed.value)
    original_transcript: Mapped[str | None] = mapped_column(Text, default=None)  # raw STT, audit
    transcript_corrected: Mapped[bool] = mapped_column(Boolean, default=False)
    transcript_confidence: Mapped[float | None] = mapped_column(Float, default=None)
    audio_storage_key: Mapped[str | None] = mapped_column(String(255), default=None)
    audio_duration_ms: Mapped[int | None] = mapped_column(Integer, default=None)

    # Classification and answer quality
    detected_mode: Mapped[str | None] = mapped_column(String(20), default=None)
    answer_status: Mapped[str | None] = mapped_column(String(20), default=None)  # AnswerStatus

    # LLM telemetry (assistant messages only)
    llm_model: Mapped[str | None] = mapped_column(String(100), default=None)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, default=None)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, default=None)
    latency_ms: Mapped[int | None] = mapped_column(Integer, default=None)

    # Microsecond precision: a message and its reply are written in the same second,
    # and the transcript / LLM history must keep their order.
    created_at: Mapped[datetime] = mapped_column(
        PRECISE_DATETIME, server_default=func.now(6), nullable=False
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    schemes: Mapped[list["MessageScheme"]] = relationship(
        back_populates="message", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index(
            "ix_conversation_messages_conversation_id_created_at", "conversation_id", "created_at"
        ),
    )


class MessageScheme(Base):
    """Which schemes an assistant answer covered — powers 'most asked about schemes'."""

    __tablename__ = "message_schemes"

    message_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("conversation_messages.id", ondelete="CASCADE"), primary_key=True
    )
    scheme_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("schemes.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    # The assistant's verdict for this citizen: True eligible, False not, None undetermined
    eligible: Mapped[bool | None] = mapped_column(Boolean, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    message: Mapped[ConversationMessage] = relationship(back_populates="schemes")
    scheme: Mapped["Scheme"] = relationship()


class UnansweredQuestion(Base, TimestampMixin):
    """A question the assistant couldn't answer from the data — the KB improvement backlog."""

    __tablename__ = "unanswered_questions"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("conversations.id", ondelete="SET NULL"), default=None
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("conversation_messages.id", ondelete="SET NULL"), default=None
    )
    district_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("districts.id", ondelete="SET NULL"), default=None
    )
    question: Mapped[str] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(5), default=None)
    reason: Mapped[str | None] = mapped_column(String(20), default=None)  # AnswerStatus
    status: Mapped[str] = mapped_column(String(20), default=UnansweredStatus.open.value, index=True)
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    review_note: Mapped[str | None] = mapped_column(Text, default=None)
