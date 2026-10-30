"""The citizen's conversations with the scheme / grievance assistant."""

import uuid

import redis.asyncio as redis
from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile, WebSocket
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import authorized_user, get_redis
from app.core.config import settings
from app.core.ratelimit import limiter
from app.db.session import get_db
from app.models.user import User
from app.schemas.assistant import (
    ChatMessageIn,
    ChatTurnOut,
    ConversationOut,
    ConversationSummaryOut,
    Lang,
    TranscriptionOut,
)
from app.schemas.common import Envelope
from app.services import assistant_service, live_voice, voice_service

router = APIRouter()


@router.post("/conversations/messages", response_model=Envelope[ChatTurnOut])
async def send_message(
    payload: ChatMessageIn,
    user: User = Depends(authorized_user),
    db: AsyncSession = Depends(get_db),
) -> Envelope[ChatTurnOut]:
    """Send a message (starting a conversation if ``conversation_id`` is omitted)
    and get the assistant's grounded reply."""
    turn = await assistant_service.post_message(
        db,
        user,
        text=payload.text.strip(),
        language=payload.language,
        conversation_id=payload.conversation_id,
        voice_token=payload.voice_token,
    )
    return Envelope[ChatTurnOut](data=turn)


@router.post("/conversations/transcriptions", response_model=Envelope[TranscriptionOut])
@limiter.limit(settings.rate_limit_voice)
async def transcribe(
    request: Request,
    audio: UploadFile = File(...),
    language: Lang = Form(default="pa"),
    duration_ms: int | None = Form(default=None, ge=0),
    user: User = Depends(authorized_user),
) -> Envelope[TranscriptionOut]:
    """Turn a recorded voice clip into text. Nothing is sent to the assistant:
    the citizen checks the text, then sends it to ``/conversations/messages``
    with the returned ``voice_token``."""
    data = await audio.read(settings.stt_max_bytes + 1)
    result = await voice_service.transcribe(
        user,
        audio=data,
        content_type=audio.content_type,
        language=language,
        duration_ms=duration_ms,
    )
    return Envelope[TranscriptionOut](
        data=TranscriptionOut(
            text=result.text, language=result.language, voice_token=result.voice_token
        )
    )


@router.get("/conversations", response_model=Envelope[list[ConversationSummaryOut]])
async def list_conversations(
    user: User = Depends(authorized_user), db: AsyncSession = Depends(get_db)
) -> Envelope[list[ConversationSummaryOut]]:
    return Envelope[list[ConversationSummaryOut]](
        data=await assistant_service.list_conversations(db, user)
    )


@router.get("/conversations/{conversation_id}", response_model=Envelope[ConversationOut])
async def get_conversation(
    conversation_id: uuid.UUID,
    user: User = Depends(authorized_user),
    db: AsyncSession = Depends(get_db),
) -> Envelope[ConversationOut]:
    return Envelope[ConversationOut](
        data=await assistant_service.get_conversation(db, user, conversation_id)
    )


@router.post("/conversations/messages/{message_id}/speech")
@limiter.limit(settings.rate_limit_speech)
async def speak(
    request: Request,
    message_id: uuid.UUID,
    user: User = Depends(authorized_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """One of your assistant replies read aloud, as a WAV file (not JSON).
    Scheme cards are not read out; they stay on screen."""
    result = await voice_service.speak_message(db, user, message_id)
    return Response(
        content=result.audio,
        media_type=result.mime_type,
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.websocket("/conversations/live-transcription")
async def live_transcription(
    websocket: WebSocket,
    language: Lang = "pa",
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
) -> None:
    """Stream microphone audio, get words back while speaking. Protocol in
    ``app/services/live_voice.py``; the result plugs into ``/conversations/messages``."""
    await live_voice.run(websocket, language, db=db, redis_client=redis_client)
