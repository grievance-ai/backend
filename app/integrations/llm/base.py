"""LLM provider interface.

The assistant only ever asks for *structured JSON* matching a schema, so every
provider exposes one call: ``generate_json``. Swapping providers (spec §8) means
adding a class here and a branch in ``get_provider`` — no business logic changes.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class LLMMessage:
    role: Literal["user", "assistant"]
    text: str


@dataclass(frozen=True)
class LLMResult:
    data: dict[str, Any]
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_ms: int | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


class LLMError(RuntimeError):
    """The provider failed (network, quota, safety block, or unparsable output)."""


class LLMProvider(ABC):
    name: str

    @abstractmethod
    async def generate_json(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        schema: dict[str, Any],
        max_output_tokens: int,
    ) -> LLMResult:
        """Return the model's answer parsed as JSON matching ``schema``.

        ``schema`` uses the OpenAPI-subset format (``"type": "OBJECT"`` etc.).
        Raise ``LLMError`` on any failure.
        """
