"""Official-website search: the fallback when a scheme is not in the verified list.

Flow: the assistant's reply is marked ``official_search: "pending"``; the app shows
a "checking official government websites" animation and calls
``POST /conversations/messages/{id}/official-search``, which runs ``run`` below.

Safety rules, enforced here rather than trusted to the provider:
- Only sentences backed by a page on an allowlisted domain (``WEBSEARCH_ALLOWED_DOMAINS``,
  matched on the real hostname) are kept. Unbacked or non-official sentences are dropped.
- Every link shown is to an allowlisted domain. Provider redirect links are resolved
  first; a link that cannot be confirmed as official is not shown.
- The answer is stored and shown as "from official websites, not verified by us".
- Results are cached per question and language for ``WEBSEARCH_CACHE_SECONDS``.
"""

import asyncio
import datetime as dt
import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from urllib.parse import urlsplit

import httpx
import redis.asyncio as redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import APIError
from app.core.logging import get_logger
from app.integrations import websearch
from app.integrations.websearch import GroundedAnswer, WebSearchError
from app.models.conversation import Conversation, ConversationMessage
from app.models.enums import AnswerStatus, MessageRole
from app.models.user import User
from app.schemas.assistant import MessageOut

logger = get_logger(__name__)

MAX_SOURCES = 3
_REDIRECT_HOSTS = ("vertexaisearch.cloud.google.com",)
_SPACES = re.compile(r"\s+")

# The sentence added to the assistant's reply while the search runs (also spoken
# in hands-free mode), and the replies when nothing official is found.
CHECKING = {
    "en": "Checking official government websites now…",
    "pa": "ਹੁਣ ਸਰਕਾਰੀ ਵੈੱਬਸਾਈਟਾਂ ਦੀ ਜਾਂਚ ਕੀਤੀ ਜਾ ਰਹੀ ਹੈ…",
}
NOT_FOUND = {
    "en": (
        "I couldn't find this on official government websites either. Please ask at "
        "your nearest Sewa Kendra or the department's office."
    ),
    "pa": (
        "ਇਹ ਜਾਣਕਾਰੀ ਸਰਕਾਰੀ ਵੈੱਬਸਾਈਟਾਂ 'ਤੇ ਵੀ ਨਹੀਂ ਮਿਲੀ। ਕਿਰਪਾ ਕਰਕੇ ਆਪਣੇ ਨੇੜਲੇ "
        "ਸੇਵਾ ਕੇਂਦਰ ਜਾਂ ਸਬੰਧਤ ਵਿਭਾਗ ਦੇ ਦਫ਼ਤਰ ਤੋਂ ਪਤਾ ਕਰੋ।"
    ),
}
UNAVAILABLE = {
    "en": (
        "I couldn't reach official government websites just now. Please try again in "
        "a little while, or ask at your nearest Sewa Kendra."
    ),
    "pa": (
        "ਇਸ ਵੇਲੇ ਸਰਕਾਰੀ ਵੈੱਬਸਾਈਟਾਂ ਤੱਕ ਪਹੁੰਚ ਨਹੀਂ ਹੋ ਸਕੀ। ਕਿਰਪਾ ਕਰਕੇ ਥੋੜ੍ਹੀ ਦੇਰ "
        "ਬਾਅਦ ਦੁਬਾਰਾ ਕੋਸ਼ਿਸ਼ ਕਰੋ, ਜਾਂ ਆਪਣੇ ਨੇੜਲੇ ਸੇਵਾ ਕੇਂਦਰ ਤੋਂ ਪਤਾ ਕਰੋ।"
    ),
}
LANGUAGE_NAMES = {"en": "English", "pa": "Punjabi, written in Gurmukhi script"}


def _say(table: dict[str, str], language: str) -> str:
    return table.get(language, table["en"])


def checking_text(language: str) -> str:
    return _say(CHECKING, language)


# --- the allowlist ---------------------------------------------------------------


def _host(value: str) -> str:
    """The lower-case hostname of a URL, or of a bare domain like "pmkisan.gov.in"."""
    value = value.strip().lower()
    host = urlsplit(value if "://" in value else f"https://{value}").hostname or ""
    return host.rstrip(".")


def is_official(value: str) -> bool:
    """Whether a URL or domain is on an allowlisted government domain.

    Matches whole labels only: "pmkisan.gov.in" yes; "gov.in.example.com" and
    "fakegov.in" no."""
    host = _host(value)
    return any(
        host == suffix or host.endswith(f".{suffix}")
        for suffix in settings.websearch_allowed_suffixes
    )


async def _resolve(client: httpx.AsyncClient, url: str) -> str | None:
    """The page a provider redirect link points to (one hop, not followed)."""
    if _host(url) not in _REDIRECT_HOSTS:
        return url
    try:
        resp = await client.get(url, follow_redirects=False)
    except httpx.HTTPError:
        return None
    location = resp.headers.get("location")
    return location if resp.is_redirect and location else None


# --- filtering ------------------------------------------------------------------------


@dataclass
class OfficialAnswer:
    found: bool
    text: str = ""
    sources: list[dict[str, str]] = field(default_factory=list)  # {"url", "title"}
    error: bool = False  # the search itself failed (not cached)


async def filter_official(answer: GroundedAnswer) -> OfficialAnswer:
    """Keep only what official pages back, with links to those pages."""
    used = sorted({i for s in answer.supports for i in s.pages if 0 <= i < len(answer.pages)})
    async with httpx.AsyncClient(timeout=4.0) as client:
        resolved = await asyncio.gather(*(_resolve(client, answer.pages[i].url) for i in used))

    official: dict[int, dict[str, str]] = {}
    for i, url in zip(used, resolved, strict=True):
        page = answer.pages[i]
        if url is not None:
            if is_official(url):
                official[i] = {"url": url, "title": page.title or _host(url)}
        elif page.title and is_official(page.title):
            # The redirect could not be followed: Google's metadata names the site,
            # so link to the site's home page rather than an unchecked address.
            official[i] = {"url": f"https://{_host(page.title)}/", "title": _host(page.title)}

    kept: list[str] = []
    sources: list[dict[str, str]] = []
    for support in answer.supports:
        backers = [i for i in support.pages if i in official]
        sentence = _SPACES.sub(" ", support.text).strip()
        if not backers or not sentence or sentence in kept:
            continue
        kept.append(sentence)
        for i in backers:
            if official[i] not in sources:
                sources.append(official[i])

    dropped = len(answer.supports) - len(kept)
    if dropped:
        logger.info("official_search_dropped", sentences=dropped, kept=len(kept))
    if not kept:
        return OfficialAnswer(found=False)
    return OfficialAnswer(found=True, text=" ".join(kept), sources=sources[:MAX_SOURCES])


# --- search with cache -----------------------------------------------------------------


def _cache_key(question: str, language: str) -> str:
    normal = _SPACES.sub(" ", question.strip().lower())
    return "websearch:" + hashlib.sha256(f"{language}|{normal}".encode()).hexdigest()


async def search(redis_client: redis.Redis, *, question: str, language: str) -> OfficialAnswer:
    key = _cache_key(question, language)
    cached = await redis_client.get(key)
    if cached:
        return OfficialAnswer(**json.loads(cached))
    try:
        grounded = await asyncio.wait_for(
            websearch.get_provider().answer(
                question=question, language_name=LANGUAGE_NAMES.get(language, "English")
            ),
            timeout=settings.websearch_timeout_seconds,
        )
    except (WebSearchError, TimeoutError) as exc:
        logger.warning("official_search_failed", error=str(exc) or exc.__class__.__name__)
        return OfficialAnswer(found=False, error=True)

    result = await filter_official(grounded)
    logger.info(
        "official_search_done",
        found=result.found,
        sources=[s["url"] for s in result.sources],
        queries=grounded.queries,
        model=grounded.model,
        latency_ms=grounded.latency_ms,
    )
    await redis_client.set(key, json.dumps(asdict(result)), ex=settings.websearch_cache_seconds)
    return result


# --- the conversation step ----------------------------------------------------------------


async def run(
    db: AsyncSession, redis_client: redis.Redis, user: User, message_id: uuid.UUID
) -> MessageOut:
    """Search official websites for the question behind a "pending" reply, and add
    the result to the conversation as a new assistant message. Safe to repeat:
    a second call returns the same result message."""
    from app.services.assistant_service import message_out  # avoid an import cycle

    reply = await db.scalar(
        select(ConversationMessage)
        .join(Conversation, Conversation.id == ConversationMessage.conversation_id)
        .where(ConversationMessage.id == message_id, Conversation.user_id == user.id)
        .with_for_update()  # a double tap runs one search, not two
    )
    if reply is None or reply.role != MessageRole.assistant.value:
        raise APIError(["resource.conversation.message_not_found"], 404)
    payload = reply.payload or {}
    if payload.get("official_search") == "done" and payload.get("official_result_id"):
        existing = await db.get(ConversationMessage, uuid.UUID(payload["official_result_id"]))
        if existing is not None:
            return message_out(existing)
    if payload.get("official_search") != "pending":
        raise APIError(["resource.conversation.no_official_search"], 409)

    question = await db.scalar(
        select(ConversationMessage.content)
        .where(
            ConversationMessage.conversation_id == reply.conversation_id,
            ConversationMessage.role == MessageRole.citizen.value,
            ConversationMessage.created_at < reply.created_at,
        )
        .order_by(ConversationMessage.created_at.desc())
        .limit(1)
    )
    language = reply.language or "en"
    result = await search(redis_client, question=question or "", language=language)

    if result.found:
        content, status = result.text, AnswerStatus.official_web.value
    else:
        content = _say(UNAVAILABLE if result.error else NOT_FOUND, language)
        status = AnswerStatus.not_in_data.value
    now = dt.datetime.now(dt.UTC)
    message = ConversationMessage(
        conversation_id=reply.conversation_id,
        role=MessageRole.assistant.value,
        content=content,
        language=language,
        payload={"web": {"found": result.found, "sources": result.sources}},
        answer_status=status,
        created_at=now,
    )
    db.add(message)
    await db.flush()
    reply.payload = {**payload, "official_search": "done", "official_result_id": str(message.id)}
    conversation = await db.get(Conversation, reply.conversation_id)
    if conversation is not None:
        conversation.last_message_at = now
    await db.commit()
    await db.refresh(message)
    return message_out(message)
