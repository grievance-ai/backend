"""Pick the schemes the assistant should see for a question (spec §5.6).

- Small knowledge base (at most ``SCHEME_FULL_INJECTION_LIMIT`` active schemes):
  every active scheme is sent, as before. No embedding call.
- Larger: the question, plus the citizen's last couple of messages for
  follow-ups, is embedded and compared with each scheme's stored vector
  (cosine similarity). The best ``SCHEME_SHORTLIST_SIZE`` are sent, together
  with schemes already discussed in the conversation, so "tell me more about
  the second one" still works.
- If the embedding call fails, the shortlist falls back to keyword overlap, so
  a provider outage never stops the assistant.

Embeddings work across languages: a Punjabi question finds English scheme text.
Vectors live in MySQL (``scheme_embeddings``) and are searched in memory with
numpy; a few thousand schemes take milliseconds. No separate vector database.
"""

import hashlib
import re
import uuid
from typing import Any

import numpy as np
from sqlalchemy import ColumnElement, Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.logging import get_logger
from app.integrations import embeddings
from app.integrations.embeddings import EmbeddingError
from app.models.conversation import ConversationMessage, MessageScheme
from app.models.scheme import Scheme, SchemeEmbedding

logger = get_logger(__name__)

STATE_CODE = "PB"  # the platform serves Punjab: central schemes + Punjab's own
MAX_DISCUSSED = 3  # schemes from earlier answers kept in the shortlist
_WORD = re.compile(r"\w+")


def _active_filter() -> list[ColumnElement[bool]]:
    return [
        Scheme.is_active.is_(True),
        or_(Scheme.state_code.is_(None), Scheme.state_code == STATE_CODE),
    ]


def active_schemes() -> Select[tuple[Scheme]]:
    """Active central schemes and Punjab's own (what citizens and the assistant see)."""
    return select(Scheme).where(*_active_filter())


def _active() -> Select[tuple[Scheme]]:
    return active_schemes()


def _with_details(stmt: Select[tuple[Scheme]]) -> Select[tuple[Scheme]]:
    return stmt.options(selectinload(Scheme.conditions), selectinload(Scheme.department))


def embedding_text(scheme: Scheme) -> str:
    """What a scheme is "about", in one block of text."""
    parts: list[str] = [
        scheme.name,
        scheme.short_name or "",
        scheme.name_pa or "",
        f"{scheme.level} scheme",
        scheme.department.name_en if scheme.department else scheme.administering_body or "",
        scheme.description,
        scheme.benefits,
        "Eligibility: " + "; ".join(c.description for c in scheme.conditions),
        "Topics: " + ", ".join(str(t) for t in scheme.category_tags or []),
        "Keywords: " + ", ".join(str(k) for k in scheme.keywords or []),
    ]
    return "\n".join(p for p in parts if p.strip())


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _pack(vector: list[float]) -> bytes:
    array = np.asarray(vector, dtype="<f4")
    norm = float(np.linalg.norm(array)) or 1.0
    return (array / norm).astype("<f4").tobytes()  # stored normalised: dot = cosine


# --- keeping vectors up to date --------------------------------------------------------


async def refresh_embeddings(db: AsyncSession, *, force: bool = False) -> int:
    """Embed active schemes that are new or changed. Returns how many were embedded.

    Raises ``EmbeddingError`` if the provider fails.
    """
    provider = embeddings.get_provider()
    schemes = list((await db.scalars(_with_details(_active()))).all())
    existing = {
        e.scheme_id: e
        for e in await db.scalars(
            select(SchemeEmbedding).where(SchemeEmbedding.scheme_id.in_([s.id for s in schemes]))
        )
    }
    todo: list[tuple[Scheme, str]] = []
    for scheme in schemes:
        text = embedding_text(scheme)
        row = existing.get(scheme.id)
        if force or row is None or row.model != provider.model or row.content_hash != _hash(text):
            todo.append((scheme, text))
    if not todo:
        return 0

    vectors = await provider.embed([text for _, text in todo])
    for (scheme, text), vector in zip(todo, vectors, strict=True):
        row = existing.get(scheme.id)
        if row is None:
            row = SchemeEmbedding(scheme_id=scheme.id)
            db.add(row)
        row.model = provider.model
        row.content_hash = _hash(text)
        row.vector = _pack(vector)
    await db.commit()
    _matrix_cache.clear()
    logger.info("scheme_embeddings_refreshed", count=len(todo), model=provider.model)
    return len(todo)


# --- the in-memory matrix ----------------------------------------------------------------

# model -> (signature, scheme ids, matrix of normalised vectors)
_matrix_cache: dict[str, tuple[tuple[Any, ...], list[uuid.UUID], np.ndarray]] = {}


async def _matrix(db: AsyncSession, model: str) -> tuple[list[uuid.UUID], np.ndarray]:
    """All stored vectors for active schemes, reloaded only when they change."""
    active_ids = select(Scheme.id).where(*_active_filter())
    signature = tuple(
        (
            await db.execute(
                select(func.count(), func.max(SchemeEmbedding.updated_at)).where(
                    SchemeEmbedding.model == model, SchemeEmbedding.scheme_id.in_(active_ids)
                )
            )
        ).one()
    )
    cached = _matrix_cache.get(model)
    if cached and cached[0] == signature:
        return cached[1], cached[2]
    rows = (
        await db.execute(
            select(SchemeEmbedding.scheme_id, SchemeEmbedding.vector).where(
                SchemeEmbedding.model == model, SchemeEmbedding.scheme_id.in_(active_ids)
            )
        )
    ).all()
    ids = [r[0] for r in rows]
    matrix = (
        np.vstack([np.frombuffer(r[1], dtype="<f4") for r in rows])
        if rows
        else np.zeros((0, 0), dtype="<f4")
    )
    _matrix_cache[model] = (signature, ids, matrix)
    return ids, matrix


# --- the shortlist ------------------------------------------------------------------------


async def discussed_scheme_ids(db: AsyncSession, conversation_id: uuid.UUID) -> list[uuid.UUID]:
    """Schemes from this conversation's recent answers, newest first."""
    rows = await db.execute(
        select(MessageScheme.scheme_id)
        .join(ConversationMessage, ConversationMessage.id == MessageScheme.message_id)
        .where(ConversationMessage.conversation_id == conversation_id)
        .order_by(ConversationMessage.created_at.desc())
        .limit(20)
    )
    seen: list[uuid.UUID] = []
    for (scheme_id,) in rows:
        if scheme_id not in seen:
            seen.append(scheme_id)
    return seen[:MAX_DISCUSSED]


async def _keyword_rank(db: AsyncSession, query: str, limit: int) -> list[uuid.UUID]:
    """Fallback when embeddings are unavailable: words shared with the scheme's text."""
    words = {w for w in _WORD.findall(query.lower()) if len(w) > 2}
    scored: list[tuple[int, str, uuid.UUID]] = []
    for scheme in await db.scalars(_active()):
        haystack = " ".join(
            [
                scheme.name,
                scheme.short_name or "",
                scheme.name_pa or "",
                scheme.description,
                *(str(k) for k in scheme.keywords or []),
                *(str(t) for t in scheme.category_tags or []),
            ]
        ).lower()
        score = sum(1 for w in words if w in haystack)
        scored.append((score, scheme.name, scheme.id))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [scheme_id for _, _, scheme_id in scored[:limit]]


async def shortlist(
    db: AsyncSession, *, query: str, discussed: list[uuid.UUID] | None = None
) -> list[Scheme]:
    """The schemes to send to the model for this question."""
    total = int(
        await db.scalar(select(func.count()).select_from(Scheme).where(*_active_filter())) or 0
    )
    if total <= settings.scheme_full_injection_limit:
        return list((await db.scalars(_with_details(_active()).order_by(Scheme.name))).all())

    size = settings.scheme_shortlist_size
    provider = embeddings.get_provider()
    ranked: list[uuid.UUID]
    try:
        ids, matrix = await _matrix(db, provider.model)
        if not ids:
            raise EmbeddingError("no stored scheme vectors for this model")
        query_vector = np.frombuffer(_pack((await provider.embed([query]))[0]), dtype="<f4")
        scores = matrix @ query_vector
        ranked = [ids[i] for i in np.argsort(-scores)[:size]]
    except EmbeddingError as exc:
        logger.warning("scheme_search_fallback", error=str(exc))
        ranked = await _keyword_rank(db, query, size)

    wanted: list[uuid.UUID] = []
    for scheme_id in [*(discussed or [])[:MAX_DISCUSSED], *ranked]:
        if scheme_id not in wanted:
            wanted.append(scheme_id)
    rows = {
        s.id: s for s in await db.scalars(_with_details(_active().where(Scheme.id.in_(wanted))))
    }
    return [rows[i] for i in wanted if i in rows]
