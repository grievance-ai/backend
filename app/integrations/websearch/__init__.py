"""Web search provider selection: ``WEBSEARCH_PROVIDER`` (blank = ``LLM_PROVIDER``).

``none`` turns the official-website search off.
"""

from app.core.config import settings
from app.integrations.websearch.base import (
    GroundedAnswer,
    Support,
    WebPage,
    WebSearchError,
    WebSearchProvider,
)
from app.integrations.websearch.mock import MockWebSearchProvider

__all__ = [
    "GroundedAnswer",
    "Support",
    "WebPage",
    "WebSearchError",
    "WebSearchProvider",
    "get_provider",
    "is_enabled",
]


def is_enabled() -> bool:
    return settings.websearch_provider_name != "none"


def get_provider() -> WebSearchProvider:
    if settings.websearch_provider_name == "gemini":
        from app.integrations.websearch.gemini import GeminiWebSearchProvider

        return GeminiWebSearchProvider()
    return MockWebSearchProvider()
