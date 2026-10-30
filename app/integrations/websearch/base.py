"""Web search with grounded answers: what the provider found, before any filtering.

The provider returns the answer text, every web page it used, and which page
backs which sentence. ``app.services.official_search`` then keeps only the
sentences backed by official government pages, so the allowlist never depends on
the provider honouring an instruction.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class WebSearchError(Exception):
    """The search provider failed (network, quota, bad response)."""


@dataclass(frozen=True)
class WebPage:
    url: str  # may be a provider redirect link; resolved later
    title: str  # Gemini puts the site's domain here


@dataclass(frozen=True)
class Support:
    text: str  # one sentence (or part of one) of the answer
    pages: tuple[int, ...]  # indexes into GroundedAnswer.pages


@dataclass
class GroundedAnswer:
    text: str
    pages: list[WebPage] = field(default_factory=list)
    supports: list[Support] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    model: str | None = None
    latency_ms: int | None = None


class WebSearchProvider(ABC):
    @abstractmethod
    async def answer(self, *, question: str, language_name: str) -> GroundedAnswer:
        """Search the web and answer ``question`` in ``language_name``."""
