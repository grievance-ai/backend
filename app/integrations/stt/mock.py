"""Offline speech-to-text for tests and keyless dev: returns queued or canned text."""

from collections import deque

from app.integrations.stt.base import STTProvider, STTResult

_queue: deque[str] = deque()

_CANNED = {
    "en": "There is no water supply in our village for a week.",
    "pa": "ਸਾਡੇ ਪਿੰਡ ਵਿੱਚ ਇੱਕ ਹਫ਼ਤੇ ਤੋਂ ਪਾਣੀ ਨਹੀਂ ਆ ਰਿਹਾ।",
}


def queue_transcript(text: str) -> None:
    """Make the next ``transcribe`` call return ``text``."""
    _queue.append(text)


def clear() -> None:
    _queue.clear()


class MockSTTProvider(STTProvider):
    name = "mock"

    async def transcribe(self, audio: bytes, *, mime_type: str, language: str) -> STTResult:
        text = _queue.popleft() if _queue else _CANNED.get(language, _CANNED["en"])
        return STTResult(text=text, model="mock", language=language, latency_ms=0)
