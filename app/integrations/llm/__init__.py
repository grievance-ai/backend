"""LLM provider selection: ``LLM_PROVIDER`` = mock (default) | gemini."""

from app.core.config import settings
from app.integrations.llm.base import LLMError, LLMMessage, LLMProvider, LLMResult
from app.integrations.llm.mock import MockLLMProvider

__all__ = ["LLMError", "LLMMessage", "LLMProvider", "LLMResult", "get_provider"]


def get_provider() -> LLMProvider:
    if settings.llm_provider.lower() == "gemini":
        from app.integrations.llm.gemini import GeminiProvider

        return GeminiProvider()
    return MockLLMProvider()
