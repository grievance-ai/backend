"""Live voice transcription over a WebSocket: words on screen while the citizen talks.

Protocol, browser and this server (``/resource/conversations/live-transcription``):

1. Connect with the auth cookie and ``?language=pa|en``. The Origin must be one of
   ``CORS_ORIGINS``, so another site can't open a session with the citizen's cookies.
2. Server sends ``{"type": "ready"}`` once the transcription service is connected.
3. Client sends binary frames: 16 kHz mono 16-bit little-endian PCM, about 100 ms each.
4. Server sends ``{"type": "partial", "text": ...}`` (the whole text so far) as words arrive.
5. Client sends ``{"type": "end"}`` when the citizen stops (or ``{"type": "cancel"}``).
6. Server sends ``{"type": "final", "text", "voice_token"}`` (same token as the upload
   path, so ``/conversations/messages`` keeps the original transcript) or
   ``{"type": "error", "code"}``, then closes. On ``unavailable`` / ``failed`` the
   client falls back to uploading its own recording.
"""

import asyncio
import contextlib
import json

import redis.asyncio as redis
from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import user_from_access_token
from app.core.authorize import authorize
from app.core.config import settings
from app.core.errors import APIError
from app.core.logging import get_logger
from app.integrations.stt.base import STTError
from app.integrations.stt.live import SAMPLE_RATE, get_live_transcriber
from app.integrations.tts.wav import pcm_to_wav
from app.models.user import User
from app.services import voice_service

logger = get_logger(__name__)

_BYTES_PER_SECOND = SAMPLE_RATE * 2
_MIN_AUDIO_BYTES = _BYTES_PER_SECOND // 2  # half a second
_FINAL_WAIT_SECONDS = 10


async def _send_error(websocket: WebSocket, code: str) -> None:
    with contextlib.suppress(Exception):
        await websocket.send_json({"type": "error", "code": code})
        await websocket.close()


async def _authenticate(
    websocket: WebSocket, db: AsyncSession, redis_client: redis.Redis
) -> User | None:
    if websocket.headers.get("origin") not in settings.cors_origins_list:
        return None
    try:
        user = await user_from_access_token(websocket.cookies.get(settings.access_cookie_name), db)
        await authorize(db, redis_client, role=user.role, method="POST", path=websocket.url.path)
    except APIError:
        return None
    finally:
        # Don't hold a database connection for the whole conversation.
        await db.close()
    return user


async def _within_rate_limit(user: User, redis_client: redis.Redis) -> bool:
    key = f"voice-live:{user.id}"
    count = await redis_client.incr(key)
    if count == 1:
        await redis_client.expire(key, 60)
    return int(count) <= settings.stt_live_per_minute


async def run(
    websocket: WebSocket, language: str, *, db: AsyncSession, redis_client: redis.Redis
) -> None:
    user = await _authenticate(websocket, db, redis_client)
    if user is None:
        await websocket.close(code=1008)  # policy violation: refused before accepting
        return
    await websocket.accept()
    if not settings.stt_live_enabled:
        await _send_error(websocket, "unavailable")
        return
    if not await _within_rate_limit(user, redis_client):
        await _send_error(websocket, "rate_limited")
        return

    transcriber = get_live_transcriber()
    try:
        await transcriber.open()
    except STTError as exc:
        logger.warning("live_stt_unavailable", error=str(exc))
        await _send_error(websocket, "unavailable")
        return
    await websocket.send_json({"type": "ready"})

    audio = bytearray()
    max_bytes = _BYTES_PER_SECOND * settings.stt_max_seconds
    latest = ""
    final: str | None = None

    async def relay_words() -> None:
        nonlocal latest, final
        async for kind, text in transcriber.events():
            if kind == "partial":
                latest = text
                await websocket.send_json({"type": "partial", "text": text})
            else:
                final = text
                return

    words = asyncio.create_task(relay_words())
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                return  # citizen left: nothing kept
            chunk = message.get("bytes")
            if chunk:
                if len(audio) + len(chunk) > max_bytes:
                    break  # recording limit reached: finish with what we have
                audio.extend(chunk)
                await transcriber.send_audio(chunk)
                continue
            command = json.loads(message.get("text") or "{}").get("type")
            if command == "cancel":
                return
            if command == "end":
                break

        await transcriber.end()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(asyncio.shield(words), timeout=_FINAL_WAIT_SECONDS)
        if words.done() and not words.cancelled() and words.exception() is not None:
            raise STTError("live transcription failed")
        if len(audio) < _MIN_AUDIO_BYTES:
            await _send_error(websocket, "too_short")
            return

        text = final if final is not None else latest
        try:
            result = voice_service.keep_and_sign(
                user,
                text=text,
                language=language,
                audio=pcm_to_wav(bytes(audio), SAMPLE_RATE),
                mime="audio/wav",
                ext=".wav",
                duration_ms=len(audio) * 1000 // _BYTES_PER_SECOND,
            )
        except APIError:
            await _send_error(websocket, "no_speech")
            return
        logger.info(
            "voice_transcribed_live",
            seconds=round(len(audio) / _BYTES_PER_SECOND, 1),
            chars=len(result.text),
            final=final is not None,
        )
        await websocket.send_json(
            {"type": "final", "text": result.text, "voice_token": result.voice_token}
        )
        await websocket.close()
    except WebSocketDisconnect:
        return
    except (STTError, ValueError) as exc:
        logger.warning("live_stt_failed", error=str(exc))
        await _send_error(websocket, "failed")
    finally:
        words.cancel()
        await transcriber.close()
