"""Text-to-speech provider selection: ``TTS_PROVIDER`` = mock (default) | gemini."""

from app.core.config import settings
from app.integrations.tts.base import TTSError, TTSProvider, TTSResult
from app.integrations.tts.mock import MockTTSProvider

__all__ = ["TTSError", "TTSProvider", "TTSResult", "get_provider"]


def get_provider() -> TTSProvider:
    if settings.tts_provider_name == "gemini":
        from app.integrations.tts.gemini import GeminiTTSProvider

        return GeminiTTSProvider()
    return MockTTSProvider()
