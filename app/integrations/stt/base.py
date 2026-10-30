"""Speech-to-text provider interface.

One call: ``transcribe`` turns a short voice clip into text. Swapping providers
(spec §8, e.g. Groq Whisper) means a new class here and a branch in
``get_provider``; the voice service does not change.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class STTResult:
    text: str  # empty when nothing intelligible was said
    model: str
    language: str | None = None  # "en" / "pa" as heard, if the provider reports it
    latency_ms: int | None = None


class STTError(RuntimeError):
    """The provider failed (network, quota, unsupported audio, bad output)."""


class STTProvider(ABC):
    name: str

    @abstractmethod
    async def transcribe(self, audio: bytes, *, mime_type: str, language: str) -> STTResult:
        """Transcribe ``audio``. ``language`` is the app language, a hint only:
        citizens may speak Punjabi in the English app and the reverse."""
