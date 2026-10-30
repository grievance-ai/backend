"""Citizen assistant: one conversation turn, grounded in the scheme knowledge base.

Flow for each citizen message (spec §5.3, §5.6, §5.7, §9):
1. Save the citizen message.
2. Build context: citizen profile, facts already learned, all active schemes
   (full injection — the curated set is small), recent history.
3. Ask the LLM for a structured JSON answer (mode, status, reply, schemes…).
4. Validate it against the database: unknown schemes are dropped, official
   links and names always come from the database, never from the model.
5. Save the assistant message, scheme mentions (analytics) and, when the data
   could not answer, an ``UnansweredQuestion`` for the admin backlog.
"""

import datetime as dt
import json
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.errors import APIError
from app.core.logging import get_logger
from app.integrations import llm
from app.integrations.llm import LLMError, LLMMessage
from app.models.citizen_profile import CitizenProfile
from app.models.conversation import (
    Conversation,
    ConversationMessage,
    MessageScheme,
    UnansweredQuestion,
)
from app.models.enums import AnswerStatus, ConversationMode, MessageRole, MessageSource
from app.models.grievance import GrievanceCategory
from app.models.scheme import Scheme
from app.models.user import User
from app.schemas.assistant import (
    ChatTurnOut,
    ConditionOut,
    ConversationOut,
    ConversationSummaryOut,
    MessageOut,
    SchemeCardOut,
)
from app.services import voice_service
from app.services.grievance_service import DRAFT_FIELD_LIMITS

logger = get_logger(__name__)

MAX_SCHEMES_PER_ANSWER = 3
MAX_FOLLOW_UPS = 3

LANGUAGE_NAMES = {"en": "English", "pa": "Punjabi, written in Gurmukhi script"}

# Script guard. The model sometimes writes a Punjabi word in another Indian script
# (seen: a scheme name in Telugu). Replies may use Gurmukhi and the dandas (। ॥,
# which Punjabi shares with Devanagari); any other letter from the Indian script
# blocks (U+0900-U+0DFF) is a slip. Checked for the UI languages only.
_INDIC_START, _INDIC_END = 0x0900, 0x0DFF
_GURMUKHI_START, _GURMUKHI_END = 0x0A00, 0x0A7F
_DANDAS = {0x0964, 0x0965}
SCRIPT_CHECKED_LANGUAGES = frozenset(LANGUAGE_NAMES)
SCRIPT_REMINDER = (
    "Write every Punjabi word, including scheme names, in Gurmukhi letters only. "
    "Never use Telugu, Devanagari, Bengali or any other Indian script."
)

FALLBACK_REPLY = {
    "en": "Sorry, I couldn't answer just now. Please try again in a moment.",
    "pa": "ਮਾਫ਼ ਕਰਨਾ, ਮੈਂ ਹੁਣੇ ਜਵਾਬ ਨਹੀਂ ਦੇ ਸਕਿਆ। ਕਿਰਪਾ ਕਰਕੇ ਥੋੜ੍ਹੀ ਦੇਰ ਬਾਅਦ ਦੁਬਾਰਾ ਕੋਸ਼ਿਸ਼ ਕਰੋ।",
}

# --- LLM contract --------------------------------------------------------------

_STR = {"type": "STRING"}


_GRIEVANCE_FIELDS = (
    "ready_to_confirm",
    "category_code",
    "subcategory_code",
    "district",
    "location",
    "since",
    "prior_complaint",
    "summary",
    "description",
)


def _str(max_length: int) -> dict[str, Any]:
    return {"type": "STRING", "maxLength": max_length}


RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "mode": {"type": "STRING", "enum": [m.value for m in ConversationMode]},
        "answer_status": {"type": "STRING", "enum": [s.value for s in AnswerStatus]},
        "reply": _STR,
        "schemes": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "slug": _STR,
                    "eligible": {"type": "STRING", "enum": ["yes", "no", "unknown"]},
                    "summary": _STR,
                    "benefit": _STR,
                    "conditions": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "text": _STR,
                                "status": {
                                    "type": "STRING",
                                    "enum": ["met", "not_met", "unknown"],
                                },
                            },
                            "required": ["text", "status"],
                        },
                    },
                    "documents": {"type": "ARRAY", "items": _STR},
                    "steps": {"type": "ARRAY", "items": _STR},
                },
                "required": [
                    "slug",
                    "eligible",
                    "summary",
                    "benefit",
                    "conditions",
                    "documents",
                    "steps",
                ],
            },
        },
        "follow_ups": {"type": "ARRAY", "items": _str(120), "maxItems": 4},
        "facts": {
            "type": "ARRAY",
            "maxItems": 12,
            "items": {
                "type": "OBJECT",
                "properties": {"key": _STR, "value": _STR},
                "required": ["key", "value"],
            },
        },
        "grievance": {
            "type": "OBJECT",
            "nullable": True,
            "properties": {
                # maxLength is a hint only: Gemini doesn't enforce it.
                "ready_to_confirm": {"type": "BOOLEAN"},
                "category_code": _str(40),
                "subcategory_code": _str(60),
                "district": _str(80),
                "location": _str(DRAFT_FIELD_LIMITS["location"]),
                "since": _str(DRAFT_FIELD_LIMITS["since"]),
                "prior_complaint": _str(DRAFT_FIELD_LIMITS["prior_complaint"]),
                "summary": _str(DRAFT_FIELD_LIMITS["summary"]),
                "description": _str(2000),
            },
            # Every field is required (empty string when not known yet): the smaller
            # fallback model otherwise crams all details into "summary" and leaves
            # the rest out, so the draft never becomes ready for review.
            "required": list(_GRIEVANCE_FIELDS),
            # Short fields first, long text last: if the model rambles inside the
            # long text until the token cap, the short fields are already complete.
            "propertyOrdering": list(_GRIEVANCE_FIELDS),
        },
    },
    "required": ["mode", "answer_status", "reply", "schemes", "follow_ups", "facts"],
    # The grievance draft comes last: if the model rambles inside it until the token
    # cap, everything before it is complete and can be kept (see gemini._salvage).
    "propertyOrdering": [
        "mode",
        "answer_status",
        "reply",
        "schemes",
        "follow_ups",
        "facts",
        "grievance",
    ],
}

SYSTEM_PROMPT = """\
You are CitizenDesk AI, a government help assistant for citizens in Punjab, India.
You do exactly two things:
1. SCHEME ENQUIRY: explain government schemes, using ONLY the SCHEME DATA below.
2. GRIEVANCE INTAKE: help a citizen report a problem that needs government action
   (water supply, electricity, roads, sanitation, delayed applications, etc.).

STRICT RULES
- Use ONLY the SCHEME DATA. Never invent schemes, amounts, deadlines, documents,
  steps, phone numbers or links. If the data does not answer the question, set
  answer_status "not_in_data", say so plainly, and point the citizen to the
  official channel or their local government office.
- Never write URLs. Official links are attached by the system.
- You cannot browse the internet. If asked to search online, check the web or
  give the "latest" schemes, say so in ONE short sentence (you answer from
  verified scheme information that is checked against official sources), then
  STILL answer the underlying question from the SCHEME DATA. Never stop at the
  refusal, never claim you searched online or that your data is the latest.
- Broad questions ("which schemes am I eligible for?", "what can I get?") are
  scheme enquiries: pick the up to 3 schemes in the SCHEME DATA that best fit
  the CITIZEN PROFILE and KNOWN FACTS and check their conditions. Never ask the
  citizen to name a specific scheme first. If key details are missing, still
  show the best matches with "unknown" conditions and ask for the one or two
  details that would settle eligibility.
- Use the CITIZEN PROFILE and KNOWN FACTS. Never ask for anything already there.
- If eligibility depends on missing information, ask for it (one or two specific
  questions, answer_status "needs_info") instead of giving a generic answer.
- For each relevant scheme (at most 3), go condition by condition and mark each
  "met", "not_met" or "unknown" from the profile and facts. Set "eligible" to
  "yes" only if every required condition is met, "no" if any is not met,
  otherwise "unknown". Conditions with the same any_of_group need only one met.
- Translate scheme content faithfully; do not add details that are not in the data.
- Off-topic questions (not schemes or grievances): politely redirect, schemes
  empty, answer_status "off_topic".
- Grievance intake: ask ONE question at a time, never re-ask what you already know
  (profile, facts, earlier answers). You need: what happened, the exact place
  (village / mohalla / ward / street), since when, and whether they already
  complained anywhere. District comes from the profile unless they name another;
  if the profile has no district, ask for it.
  Pick category_code and subcategory_code ONLY from GRIEVANCE CATEGORIES. Put
  each detail in its own field: district, location, since, prior_complaint.
  summary is ONE short line (under 20 words) saying what is wrong and where.
  description is clear and complete, in the citizen's language, using their own
  facts — nothing invented. Never put labels like "District:" or "Ready to
  confirm" inside summary or description. Always return every grievance field
  with everything gathered so far; use "" for anything not known yet. When
  everything is collected,
  set ready_to_confirm true and in "reply" tell them to review the details and
  tap the button to register. Do not say it is registered: that happens only
  after they confirm.

OUTPUT (JSON matching the schema)
- mode: "scheme_enquiry", "grievance_intake", or "unclear" (ask a clarifying question).
- reply: plain text, no markdown, 1-4 short sentences: what was asked and which
  profile details you used, then one clear next step. Scheme details go in "schemes".
- facts: new facts the citizen just told you, as snake_case keys matching
  condition fields where possible (e.g. area=rural, owns_pucca_house=false, age=67).
- follow_ups: up to 3 short messages the citizen might tap next. Never offer to
  register, confirm or submit a grievance here: the app shows its own button.
- LANGUAGE: every text you write — reply, summary, benefit, each condition,
  each document, each step and each follow_up — MUST be in {language}. The SCHEME
  DATA is in English: translate it faithfully, never copy English sentences.
  Only official scheme names and phone numbers stay exactly as given.
"""


# --- script guard -------------------------------------------------------------


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [t for v in value.values() for t in _strings(v)]
    if isinstance(value, list):
        return [t for v in value for t in _strings(v)]
    return []


def foreign_script_count(data: dict[str, Any], language: str) -> int:
    """How many letters of the reply are in an Indian script it should not use.

    ``facts`` is skipped: it can echo the citizen's own words in any script.
    """
    if language not in SCRIPT_CHECKED_LANGUAGES:
        return 0
    count = 0
    for key, value in data.items():
        if key == "facts":
            continue
        for text in _strings(value):
            for ch in text:
                code = ord(ch)
                if (
                    _INDIC_START <= code <= _INDIC_END
                    and not _GURMUKHI_START <= code <= _GURMUKHI_END
                    and code not in _DANDAS
                ):
                    count += 1
    return count


# --- context builders ----------------------------------------------------------


def _profile_context(user: User, profile: CitizenProfile | None) -> dict[str, Any]:
    ctx: dict[str, Any] = {"name": user.name, "state": "Punjab"}
    if profile is None:
        return ctx
    ctx.update(
        {
            "district": profile.district.name_en if profile.district else None,
            "tehsil": profile.tehsil.name_en if profile.tehsil else None,
            "village": profile.village,
            "occupation": profile.occupation,
            "land_holding_acres": (
                float(profile.land_holding_acres)
                if profile.land_holding_acres is not None
                else None
            ),
            "income_band": profile.income_band,
            "social_category": profile.social_category,
            "gender": profile.gender,
            "marital_status": profile.marital_status,
            # Named "area" to match the eligibility field (e.g. PMAY-G: area = rural).
            "area": profile.area_type,
            "age": dt.date.today().year - profile.birth_year if profile.birth_year else None,
        }
    )
    if profile.extra_attributes:
        ctx.update(profile.extra_attributes)
    return {k: v for k, v in ctx.items() if v is not None}


def _scheme_context(schemes: list[Scheme]) -> list[dict[str, Any]]:
    return [
        {
            "slug": s.slug,
            "name": s.name,
            "short_name": s.short_name,
            "level": s.level,
            "department": s.department.name_en if s.department else s.administering_body,
            "description": s.description,
            "benefits": s.benefits,
            "required_documents": s.required_documents,
            "application_steps": s.application_steps,
            "deadline": s.deadline_info,
            "contact": s.contact,
            "conditions": [
                {
                    "field": c.field_name,
                    "operator": c.operator,
                    "value": c.value,
                    "description": c.description,
                    **({"any_of_group": c.group_key} if c.group_key else {}),
                }
                for c in s.conditions
            ],
        }
        for s in schemes
    ]


def _category_context(categories: list[GrievanceCategory]) -> list[dict[str, Any]]:
    return [
        {
            "code": c.code,
            "name": c.name_en,
            "sub": [{"code": s.code, "name": s.name_en} for s in c.children if s.is_active],
        }
        for c in categories
    ]


def _history_text(message: ConversationMessage) -> str:
    """Compact form of a past assistant turn for the model's memory."""
    if message.role != MessageRole.assistant.value or not message.payload:
        return message.content
    slugs = [s.get("slug") for s in message.payload.get("schemes", [])]
    if not slugs:
        return message.content
    return f"{message.content}\n[schemes discussed: {', '.join(slugs)}]"


# --- serialisation ---------------------------------------------------------------


def _utc(value: dt.datetime) -> dt.datetime:
    """MySQL DATETIME comes back naive but is stored in UTC; say so explicitly
    so clients convert to the citizen's local time correctly."""
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


def message_out(message: ConversationMessage) -> MessageOut:
    payload = message.payload or {}
    return MessageOut(
        id=message.id,
        role="assistant" if message.role == MessageRole.assistant.value else "citizen",
        content=message.content,
        language=message.language,
        created_at=_utc(message.created_at),
        source="voice" if message.source == MessageSource.voice.value else "typed",
        answer_status=message.answer_status,
        schemes=[SchemeCardOut.model_validate(s) for s in payload.get("schemes", [])],
        follow_ups=payload.get("follow_ups", []),
        grievance_ready=bool(payload.get("grievance_ready")),
    )


def _str_list(value: Any) -> list[str]:
    return [str(v) for v in value if str(v).strip()] if isinstance(value, list) else []


def _scheme_cards(raw: Any, known: dict[str, Scheme]) -> list[SchemeCardOut]:
    cards: list[SchemeCardOut] = []
    for item in raw if isinstance(raw, list) else []:
        scheme = known.get(str(item.get("slug", "")))
        if scheme is None:  # the model named a scheme that is not in our data: drop it
            logger.warning("assistant_unknown_scheme", slug=item.get("slug"))
            continue
        conditions = [
            ConditionOut(text=str(c.get("text", "")), status=c.get("status", "unknown"))
            for c in item.get("conditions", [])
            if isinstance(c, dict) and c.get("status") in {"met", "not_met", "unknown"}
        ]
        eligible = item.get("eligible")
        cards.append(
            SchemeCardOut(
                slug=scheme.slug,
                name=scheme.name,
                short_name=scheme.short_name,
                name_pa=scheme.name_pa,
                eligible=eligible if eligible in {"yes", "no", "unknown"} else "unknown",
                summary=str(item.get("summary", "")),
                benefit=str(item.get("benefit", "")),
                conditions=conditions,
                documents=_str_list(item.get("documents")),
                steps=_str_list(item.get("steps")),
                official_url=scheme.official_url,  # always from the database
                contact=scheme.contact,
            )
        )
        if len(cards) == MAX_SCHEMES_PER_ANSWER:
            break
    return cards


# --- queries ------------------------------------------------------------------------


async def _get_owned_conversation(
    db: AsyncSession, user: User, conversation_id: uuid.UUID
) -> Conversation:
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise APIError(["resource.conversation.not_found"], 404)
    return conversation


async def list_conversations(db: AsyncSession, user: User) -> list[ConversationSummaryOut]:
    rows = await db.scalars(
        select(Conversation)
        .where(Conversation.user_id == user.id)
        # Most recently active first, so a continued old chat moves to the top.
        .order_by(func.coalesce(Conversation.last_message_at, Conversation.started_at).desc())
        .limit(20)
    )
    return [ConversationSummaryOut.model_validate(c, from_attributes=True) for c in rows]


async def get_conversation(
    db: AsyncSession, user: User, conversation_id: uuid.UUID
) -> ConversationOut:
    conversation = await _get_owned_conversation(db, user, conversation_id)
    messages = await db.scalars(
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == conversation.id)
        .order_by(ConversationMessage.created_at, ConversationMessage.role.desc())
    )
    summary = ConversationSummaryOut.model_validate(conversation, from_attributes=True)
    return ConversationOut(**summary.model_dump(), messages=[message_out(m) for m in messages])


# --- the turn -----------------------------------------------------------------------


async def post_message(
    db: AsyncSession,
    user: User,
    *,
    text: str,
    language: str,
    conversation_id: uuid.UUID | None = None,
    voice_token: str | None = None,
) -> ChatTurnOut:
    now = dt.datetime.now(dt.UTC)
    # Checked before anything is written, so a bad token changes nothing.
    voice = voice_service.verify_token(voice_token, user) if voice_token else None

    if conversation_id is None:
        conversation = Conversation(user_id=user.id, language=language, started_at=now)
        db.add(conversation)
        await db.flush()
    else:
        conversation = await _get_owned_conversation(db, user, conversation_id)
        conversation.language = language

    history = list(
        (
            await db.scalars(
                select(ConversationMessage)
                .where(ConversationMessage.conversation_id == conversation.id)
                .order_by(ConversationMessage.created_at.desc())
                .limit(settings.llm_history_messages)
            )
        ).all()
    )[::-1]

    citizen_msg = ConversationMessage(
        conversation_id=conversation.id,
        role=MessageRole.citizen.value,
        content=text,
        language=language,
        source=MessageSource.typed.value,
        created_at=now,
    )
    if voice is not None:
        citizen_msg.source = MessageSource.voice.value
        citizen_msg.original_transcript = voice.original_transcript
        citizen_msg.transcript_corrected = text != voice.original_transcript.strip()
        citizen_msg.audio_storage_key = voice.audio_storage_key
        citizen_msg.audio_duration_ms = voice.audio_duration_ms
    db.add(citizen_msg)
    conversation.turn_count += 1
    conversation.title = conversation.title or text[:120]
    conversation.last_message_at = now

    profile = await db.scalar(
        select(CitizenProfile)
        .where(CitizenProfile.user_id == user.id)
        .options(selectinload(CitizenProfile.district), selectinload(CitizenProfile.tehsil))
    )
    schemes = list(
        (
            await db.scalars(
                select(Scheme)
                .where(Scheme.is_active.is_(True))
                .options(selectinload(Scheme.conditions), selectinload(Scheme.department))
                .order_by(Scheme.name)
            )
        ).all()
    )
    known = {s.slug: s for s in schemes}
    categories = list(
        (
            await db.scalars(
                select(GrievanceCategory)
                .where(GrievanceCategory.parent_id.is_(None), GrievanceCategory.is_active.is_(True))
                .options(selectinload(GrievanceCategory.children))
                .order_by(GrievanceCategory.sort_order)
            )
        ).all()
    )
    category_codes = {c.code for c in categories} | {s.code for c in categories for s in c.children}

    language_name = LANGUAGE_NAMES.get(language, "English")
    system = SYSTEM_PROMPT.format(language=language_name)
    context_block = json.dumps(
        {
            "CITIZEN PROFILE (self-declared)": _profile_context(user, profile),
            "KNOWN FACTS (from this conversation)": conversation.context or {},
            "SCHEME DATA": _scheme_context(schemes),
            "GRIEVANCE CATEGORIES": _category_context(categories),
            "GRIEVANCE DRAFT SO FAR": conversation.grievance_draft or {},
        },
        ensure_ascii=False,
        default=str,
    )
    llm_messages = [
        LLMMessage(role="user", text=f"CONTEXT\n{context_block}"),
        LLMMessage(role="assistant", text="Understood. I will answer only from this data."),
        *[
            LLMMessage(
                role="assistant" if m.role == MessageRole.assistant.value else "user",
                text=_history_text(m),
            )
            for m in history
        ],
        # Recency matters: restate the reply language right next to the question.
        LLMMessage(role="user", text=f"{text}\n\n(Answer entirely in {language_name}.)"),
    ]

    try:
        result = await llm.get_provider().generate_json(
            system=system,
            messages=llm_messages,
            schema=RESPONSE_SCHEMA,
            max_output_tokens=settings.llm_max_output_tokens,
        )
        data, failed = result.data, False
    except LLMError as exc:
        logger.warning("assistant_llm_failed", error=str(exc))
        result, data, failed = None, {}, True

    # Wrong script (e.g. Telugu letters in a Punjabi reply): ask once more with a
    # sharper reminder and keep whichever answer is cleaner.
    foreign = 0 if failed else foreign_script_count(data, language)
    if foreign:
        logger.warning("assistant_wrong_script", language=language, letters=foreign)
        retry_messages = [
            *llm_messages[:-1],
            LLMMessage(
                role="user",
                text=f"{text}\n\n(Answer entirely in {language_name}. {SCRIPT_REMINDER})",
            ),
        ]
        try:
            retry = await llm.get_provider().generate_json(
                system=system,
                messages=retry_messages,
                schema=RESPONSE_SCHEMA,
                max_output_tokens=settings.llm_max_output_tokens,
            )
        except LLMError as exc:
            logger.warning("assistant_script_retry_failed", error=str(exc))
        else:
            if foreign_script_count(retry.data, language) < foreign:
                result, data = retry, retry.data

    mode = data.get("mode") if data.get("mode") in {m.value for m in ConversationMode} else None
    status = (
        data.get("answer_status")
        if data.get("answer_status") in {s.value for s in AnswerStatus}
        else None
    )
    cards = _scheme_cards(data.get("schemes"), known)
    follow_ups = _str_list(data.get("follow_ups"))[:MAX_FOLLOW_UPS]
    reply = str(data.get("reply") or "").strip()
    reply = reply or FALLBACK_REPLY.get(language, FALLBACK_REPLY["en"])

    assistant_msg = ConversationMessage(
        conversation_id=conversation.id,
        role=MessageRole.assistant.value,
        content=reply,
        language=language,
        payload=None
        if failed
        else {"schemes": [c.model_dump() for c in cards], "follow_ups": follow_ups},
        detected_mode=mode,
        answer_status=status,
        llm_model=result.model if result else None,
        prompt_tokens=result.prompt_tokens if result else None,
        completion_tokens=result.completion_tokens if result else None,
        latency_ms=result.latency_ms if result else None,
        # A hair later than the citizen message so ordering is stable.
        created_at=now + dt.timedelta(milliseconds=1),
    )
    db.add(assistant_msg)
    await db.flush()

    for card in cards:
        db.add(
            MessageScheme(
                message_id=assistant_msg.id,
                scheme_id=known[card.slug].id,
                eligible={"yes": True, "no": False}.get(card.eligible),
            )
        )

    if status == AnswerStatus.not_in_data.value:
        db.add(
            UnansweredQuestion(
                conversation_id=conversation.id,
                message_id=citizen_msg.id,
                district_id=profile.district_id if profile else None,
                question=text,
                language=language,
                reason=status,
            )
        )

    if mode and mode != ConversationMode.unclear.value:
        conversation.mode = mode
    facts = {
        str(f["key"]): f["value"]
        for f in data.get("facts", [])
        if isinstance(f, dict) and f.get("key")
    }
    if facts:
        conversation.context = {**(conversation.context or {}), **facts}
    grievance_ready = False
    raw_grievance = data.get("grievance")
    if conversation.mode == ConversationMode.grievance_intake.value and isinstance(
        raw_grievance, dict
    ):
        # Empty values mean "not known yet": they must never erase details that
        # earlier turns already collected.
        fresh = {k: v for k, v in raw_grievance.items() if v not in ("", None)}
        draft = {**(conversation.grievance_draft or {}), **fresh}
        # A degenerate model reply can dump everything into one field; drop
        # oversized values instead of saving junk the citizen would see.
        for key, limit in DRAFT_FIELD_LIMITS.items():
            value = draft.get(key)
            if isinstance(value, str) and len(value) > limit:
                draft.pop(key)
        for key in ("category_code", "subcategory_code"):  # only codes we actually have
            if draft.get(key) not in category_codes:
                draft.pop(key, None)
        conversation.grievance_draft = draft
        # A summary alone is enough to open the review screen, which falls back to
        # it for the description (grievance_service.get_draft).
        grievance_ready = bool(
            draft.get("ready_to_confirm")
            and draft.get("category_code")
            and (draft.get("description") or draft.get("summary"))
        )
    if assistant_msg.payload is not None and grievance_ready:
        assistant_msg.payload = {**assistant_msg.payload, "grievance_ready": True}

    await db.commit()
    await db.refresh(citizen_msg)
    await db.refresh(assistant_msg)
    return ChatTurnOut(
        conversation_id=conversation.id,
        mode=conversation.mode,
        user_message=message_out(citizen_msg),
        assistant_message=message_out(assistant_msg),
    )
