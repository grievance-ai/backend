"""Offline web search for tests: queue grounded answers, or get nothing found."""

from app.integrations.websearch.base import GroundedAnswer, WebSearchError, WebSearchProvider

_queue: list[GroundedAnswer | WebSearchError] = []


def queue_answer(answer: GroundedAnswer | WebSearchError) -> None:
    _queue.append(answer)


def reset() -> None:
    _queue.clear()
    MockWebSearchProvider.calls = 0


class MockWebSearchProvider(WebSearchProvider):
    calls = 0

    async def answer(self, *, question: str, language_name: str) -> GroundedAnswer:
        MockWebSearchProvider.calls += 1
        item = _queue.pop(0) if _queue else GroundedAnswer(text="")
        if isinstance(item, WebSearchError):
            raise item
        return item
