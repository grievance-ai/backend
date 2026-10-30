"""Streaming speech-to-text: words while the citizen is still talking.

A ``LiveTranscriber`` takes 16 kHz mono 16-bit PCM in small chunks and yields
``("partial", text)`` updates (the whole text so far) and one ``("final", text)``
after ``end()``. The Gemini version relays to the Live API transcription model
over a WebSocket; the API key never leaves the server.
"""

import asyncio
import base64
import contextlib
import json
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import AsyncIterator
from typing import Any, Literal

import websockets

from app.core.config import settings
from app.core.logging import get_logger
from app.integrations.stt.base import STTError

logger = get_logger(__name__)

SAMPLE_RATE = 16_000
Event = tuple[Literal["partial", "final"], str]

_LIVE_URL = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
)


class LiveTranscriber(ABC):
    @abstractmethod
    async def open(self) -> None:
        """Connect; raise ``STTError`` if the service is unavailable."""

    @abstractmethod
    async def send_audio(self, pcm: bytes) -> None: ...

    @abstractmethod
    async def end(self) -> None:
        """No more audio: the service should finish and send the final text."""

    @abstractmethod
    def events(self) -> AsyncIterator[Event]:
        """Partial updates, then one final text (empty if nothing was said)."""

    @abstractmethod
    async def close(self) -> None: ...


class GeminiLiveTranscriber(LiveTranscriber):
    def __init__(self) -> None:
        if not settings.gemini_api_key:
            raise STTError("GEMINI_API_KEY is not set")
        self._ws: Any = None
        self._ended = False

    async def open(self) -> None:
        try:
            self._ws = await websockets.connect(
                _LIVE_URL,
                additional_headers={"x-goog-api-key": settings.gemini_api_key},
                max_size=None,
                open_timeout=8,
            )
            await self._ws.send(
                json.dumps(
                    {
                        "setup": {
                            "model": f"models/{settings.stt_live_model}",
                            "inputAudioTranscription": {},
                        }
                    }
                )
            )
            reply = json.loads(await asyncio.wait_for(self._ws.recv(), timeout=8))
        except (OSError, TimeoutError, websockets.WebSocketException, ValueError) as exc:
            await self.close()
            raise STTError(f"live transcription unavailable: {exc.__class__.__name__}") from exc
        if "setupComplete" not in reply:
            await self.close()
            raise STTError("live transcription setup was refused")

    async def send_audio(self, pcm: bytes) -> None:
        if self._ws is None or self._ended:
            return
        message = {
            "realtimeInput": {
                "audio": {
                    "mimeType": f"audio/pcm;rate={SAMPLE_RATE}",
                    "data": base64.b64encode(pcm).decode("ascii"),
                }
            }
        }
        try:
            await self._ws.send(json.dumps(message))
        except websockets.WebSocketException as exc:
            raise STTError("live transcription connection lost") from exc

    async def end(self) -> None:
        if self._ws is None or self._ended:
            return
        self._ended = True
        with contextlib.suppress(websockets.WebSocketException):
            await self._ws.send(json.dumps({"realtimeInput": {"audioStreamEnd": True}}))

    async def events(self) -> AsyncIterator[Event]:
        if self._ws is None:
            raise STTError("live transcription is not open")
        latest = ""
        try:
            async for raw in self._ws:
                content = json.loads(raw).get("serverContent", {})
                interim = content.get("interimInputTranscription", {}).get("text")
                if interim:
                    latest = interim
                    yield ("partial", interim)
                final = content.get("inputTranscription", {}).get("text")
                if final is not None:
                    yield ("final", final.strip())
                    return
                # Nothing was said: the turn completes without any transcription.
                if self._ended and content.get("generationComplete"):
                    yield ("final", latest.strip())
                    return
        except websockets.WebSocketException as exc:
            raise STTError("live transcription connection lost") from exc
        yield ("final", latest.strip())

    async def close(self) -> None:
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()
            self._ws = None


# --- Mock (tests) -------------------------------------------------------------

_queue: deque[str] = deque()


def queue_live_transcript(text: str) -> None:
    """The next mock session transcribes to ``text`` (partials grow word by word)."""
    _queue.append(text)


def clear() -> None:
    _queue.clear()


class MockLiveTranscriber(LiveTranscriber):
    def __init__(self) -> None:
        self._text = _queue.popleft() if _queue else "No water in our village for a week."
        self._words = self._text.split()
        self._events: asyncio.Queue[Event | None] = asyncio.Queue()
        self._chunks = 0

    async def open(self) -> None:
        return None

    async def send_audio(self, pcm: bytes) -> None:
        self._chunks += 1
        if self._words:
            await self._events.put(("partial", " ".join(self._words[: self._chunks])))

    async def end(self) -> None:
        await self._events.put(("final", self._text if self._chunks else ""))
        await self._events.put(None)

    async def events(self) -> AsyncIterator[Event]:
        while (event := await self._events.get()) is not None:
            yield event

    async def close(self) -> None:
        return None


def get_live_transcriber() -> LiveTranscriber:
    if settings.stt_provider_name == "gemini":
        return GeminiLiveTranscriber()
    return MockLiveTranscriber()
