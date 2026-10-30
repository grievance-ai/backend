"""Offline provider for tests and local dev without an API key.

Returns whatever was queued with ``queue_response``; otherwise an honest
"not in data" answer. Every call is recorded in ``calls`` for assertions.
"""

from typing import Any

from app.integrations.llm.base import LLMMessage, LLMProvider, LLMResult

calls: list[dict[str, Any]] = []
_queued: list[dict[str, Any]] = []


def queue_response(data: dict[str, Any]) -> None:
    _queued.append(data)


def clear() -> None:
    calls.clear()
    _queued.clear()


DEFAULT_RESPONSE: dict[str, Any] = {
    "mode": "unclear",
    "answer_status": "not_in_data",
    "reply": "I'm not able to answer that from the scheme information I have.",
    "schemes": [],
    "follow_ups": [],
    "facts": [],
}


class MockLLMProvider(LLMProvider):
    name = "mock"

    async def generate_json(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        schema: dict[str, Any],
        max_output_tokens: int,
    ) -> LLMResult:
        calls.append({"system": system, "messages": messages, "schema": schema})
        data = _queued.pop(0) if _queued else dict(DEFAULT_RESPONSE)
        return LLMResult(
            data=data, model="mock", prompt_tokens=0, completion_tokens=0, latency_ms=0
        )
