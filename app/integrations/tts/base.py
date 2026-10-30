"""Text-to-speech provider interface.

One call: ``synthesize`` turns a reply into playable audio (WAV). Swapping
providers means a new class here and a branch in ``get_provider``.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class TTSResult:
    audio: bytes
    mime_type: str  # what the browser is told to play, e.g. "audio/wav"
    model: str
    latency_ms: int | None = None


class TTSError(RuntimeError):
    """The provider failed (network, quota, empty audio)."""


class TTSProvider(ABC):
    name: str

    @abstractmethod
    async def synthesize(self, text: str, *, language: str) -> TTSResult:
        """Speak ``text`` (``language`` "en" or "pa") and return the audio."""
