"""Voice in and out: transcribe citizen clips, and read assistant replies aloud.

Voice in: store the clip, transcribe it, and vouch for the transcript.

Flow (spec: every voice flow has a typed fallback; keep original and corrected text):
1. ``transcribe`` stores the audio, runs speech-to-text and returns the text plus a
   signed ``voice_token`` holding the original transcript.
2. The citizen reads and fixes the text in the chat box, then sends it with the token.
3. ``verify_token`` (called by the assistant) recovers the original transcript, so the
   message keeps both versions. The client can't forge or swap the original, and
   the token only works for the citizen it was issued to.
"""

import datetime as dt
import hashlib
import hmac
import re
import uuid
from dataclasses import dataclass
from typing import Any

import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import APIError
from app.core.logging import get_logger
from app.integrations import storage, stt, tts
from app.models.conversation import Conversation, ConversationMessage
from app.models.enums import MessageRole
from app.models.user import User

logger = get_logger(__name__)

_AUDIENCE = "voice-transcript"
_ALGORITHM = "HS256"


def signing_key() -> bytes:
    """A 32-byte key just for these tokens, derived from ``SECRET_KEY``."""
    return hmac.new(settings.secret_key.encode(), _AUDIENCE.encode(), hashlib.sha256).digest()


# What browsers record (Chrome/Edge: webm, Firefox: ogg, Safari: mp4) plus common
# uploads. Codec parameters ("audio/webm;codecs=opus") are stripped first.
AUDIO_TYPES: dict[str, str] = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/aac": ".aac",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/flac": ".flac",
}

# Below this a clip is almost certainly an accidental tap.
_MIN_BYTES = 1000


@dataclass(frozen=True)
class Transcription:
    text: str
    language: str | None
    voice_token: str


@dataclass(frozen=True)
class VoiceOrigin:
    """What the server transcribed, recovered from a verified token."""

    original_transcript: str
    audio_storage_key: str | None
    audio_duration_ms: int | None


def _base_type(content_type: str | None) -> str:
    return (content_type or "").split(";", 1)[0].strip().lower()


def _issue_token(user: User, *, text: str, audio_key: str | None, duration_ms: int | None) -> str:
    now = dt.datetime.now(dt.UTC)
    claims: dict[str, Any] = {
        "aud": _AUDIENCE,
        "sub": str(user.id),
        "iat": now,
        "exp": now + dt.timedelta(seconds=settings.stt_token_ttl),
        "txt": text,
        "key": audio_key,
        "dur": duration_ms,
    }
    return jwt.encode(claims, signing_key(), algorithm=_ALGORITHM)


def verify_token(token: str, user: User) -> VoiceOrigin:
    """The transcript a token vouches for. 422 if it is invalid, expired or someone else's."""
    try:
        claims = jwt.decode(
            token,
            signing_key(),
            algorithms=[_ALGORITHM],
            audience=_AUDIENCE,
            options={"require": ["exp", "sub", "txt"]},
        )
    except jwt.PyJWTError as exc:
        raise APIError(["resource.voice.invalid_token"], 422) from exc
    if claims["sub"] != str(user.id) or not isinstance(claims["txt"], str):
        raise APIError(["resource.voice.invalid_token"], 422)
    key = claims.get("key")
    duration = claims.get("dur")
    return VoiceOrigin(
        original_transcript=claims["txt"],
        audio_storage_key=key if isinstance(key, str) else None,
        audio_duration_ms=duration if isinstance(duration, int) else None,
    )


async def transcribe(
    user: User,
    *,
    audio: bytes,
    content_type: str | None,
    language: str,
    duration_ms: int | None,
) -> Transcription:
    mime = _base_type(content_type)
    ext = AUDIO_TYPES.get(mime)
    if ext is None:
        raise APIError(["resource.voice.unsupported_format"], 422)
    if len(audio) < _MIN_BYTES:
        raise APIError(["resource.voice.too_short"], 422)
    if len(audio) > settings.stt_max_bytes:
        raise APIError(["resource.voice.too_large"], 422)
    if duration_ms is not None:
        duration_ms = max(0, min(duration_ms, settings.stt_max_seconds * 1000))

    try:
        result = await stt.get_provider().transcribe(audio, mime_type=mime, language=language)
    except stt.STTError as exc:
        logger.warning("stt_failed", error=str(exc))
        raise APIError(["resource.voice.transcription_failed"], 502) from exc

    logger.info(
        "voice_transcribed",
        model=result.model,
        latency_ms=result.latency_ms,
        bytes=len(audio),
        chars=len(result.text),
    )
    return keep_and_sign(
        user,
        text=result.text,
        language=result.language,
        audio=audio,
        mime=mime,
        ext=ext,
        duration_ms=duration_ms,
    )


def keep_and_sign(
    user: User,
    *,
    text: str,
    language: str | None,
    audio: bytes,
    mime: str,
    ext: str,
    duration_ms: int | None,
) -> Transcription:
    """Store the clip and sign the transcript. Shared by upload and live transcription."""
    text = text.strip()[:2000]  # the chat message limit
    if not text:
        # Nothing to keep: no speech means no stored audio either.
        raise APIError(["resource.voice.no_speech"], 422)

    # Keep the clip for the audit trail (officers can check what was said). Storage
    # failure must not cost the citizen their message, so it is logged and skipped.
    audio_key: str | None = None
    try:
        audio_key = (
            storage.get_provider()
            .upload(
                audio,
                filename=f"voice-{uuid.uuid4().hex}{ext}",
                content_type=mime,
                user_id=user.id,
                document_id=None,
            )
            .path
        )
    except Exception as exc:  # any backend error: the transcript still counts
        logger.warning("voice_audio_not_stored", error=exc.__class__.__name__)

    return Transcription(
        text=text,
        language=language,
        voice_token=_issue_token(user, text=text, audio_key=audio_key, duration_ms=duration_ms),
    )


# --- Voice out: spoken replies ----------------------------------------------

_MARKUP = re.compile(r"https?://\S+|[*_#`>\[\]]")
_SENTENCE_END = re.compile(r"[.!?।](\s|$)")


def speakable(text: str, limit: int) -> str:
    """Reply text as it should sound: no links or markdown symbols, and cut at a
    sentence end when it is longer than ``limit``."""
    clean = " ".join(_MARKUP.sub(" ", text).split())
    if len(clean) <= limit:
        return clean
    head = clean[:limit]
    ends = [m.end() for m in _SENTENCE_END.finditer(head)]
    return head[: ends[-1]].strip() if ends else head


async def speak_message(db: AsyncSession, user: User, message_id: uuid.UUID) -> tts.TTSResult:
    """Audio of one of the citizen's assistant replies. 404 for anyone else's."""
    message = await db.scalar(
        select(ConversationMessage)
        .join(Conversation, Conversation.id == ConversationMessage.conversation_id)
        .where(ConversationMessage.id == message_id, Conversation.user_id == user.id)
    )
    if message is None or message.role != MessageRole.assistant.value:
        raise APIError(["resource.conversation.message_not_found"], 404)

    text = speakable(message.content, settings.tts_max_chars)
    if not text:
        raise APIError(["resource.voice.nothing_to_say"], 422)
    language = message.language if message.language in ("en", "pa") else "pa"
    try:
        result = await tts.get_provider().synthesize(text, language=language)
    except tts.TTSError as exc:
        logger.warning("tts_failed", error=str(exc))
        raise APIError(["resource.voice.speech_failed"], 502) from exc
    logger.info(
        "reply_spoken",
        model=result.model,
        latency_ms=result.latency_ms,
        chars=len(text),
        bytes=len(result.audio),
    )
    return result
