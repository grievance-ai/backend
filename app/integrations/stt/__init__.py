"""Speech-to-text provider selection: ``STT_PROVIDER`` = mock (default) | gemini."""

from app.core.config import settings
from app.integrations.stt.base import STTError, STTProvider, STTResult
from app.integrations.stt.mock import MockSTTProvider

__all__ = ["STTError", "STTProvider", "STTResult", "get_provider"]


def get_provider() -> STTProvider:
    if settings.stt_provider_name == "gemini":
        from app.integrations.stt.gemini import GeminiSTTProvider

        return GeminiSTTProvider()
    return MockSTTProvider()
