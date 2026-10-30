"""Google Gemini provider (REST ``generateContent`` with JSON-schema output).

``call_gemini`` and ``parse_json_output`` are shared with the speech-to-text
provider (``app/integrations/stt/gemini.py``), which sends audio to the same API.
"""

import json
import re
import time
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.integrations.llm.base import LLMError, LLMMessage, LLMProvider, LLMResult

logger = get_logger(__name__)

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
# Overloaded / rate-limited / transient: worth one try on the fallback model.
_RETRY_WITH_FALLBACK = {429, 500, 503}


def model_chain(primary: str) -> list[str]:
    """The model to try first, then ``LLM_FALLBACK_MODEL`` if it differs."""
    models = [primary]
    if settings.llm_fallback_model and settings.llm_fallback_model != primary:
        models.append(settings.llm_fallback_model)
    return models


async def call_gemini(
    *, api_key: str, models: list[str], body: dict[str, Any]
) -> tuple[dict[str, Any], str, int]:
    """POST ``body`` to each model in turn until one answers.

    Moves to the next model only on overload/rate-limit errors. Returns
    ``(payload, model_used, latency_ms)``; raises ``LLMError`` on failure.
    """
    started = time.monotonic()
    model = models[0]
    resp: httpx.Response | None = None
    payload: dict[str, Any] = {}
    for model in models:
        try:
            async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
                resp = await client.post(
                    f"{_BASE_URL}/{model}:generateContent",
                    headers={"x-goog-api-key": api_key},  # header, never the URL
                    json=body,
                )
        except httpx.HTTPError as exc:
            raise LLMError(f"gemini request failed: {exc.__class__.__name__}") from exc
        payload = resp.json() if resp.content else {}
        if resp.status_code == 200:
            break
        message = payload.get("error", {}).get("message", resp.text[:200])
        logger.warning("gemini_error", model=model, status=resp.status_code, message=message)
        if resp.status_code not in _RETRY_WITH_FALLBACK:
            break
    latency_ms = int((time.monotonic() - started) * 1000)

    if resp is None or resp.status_code != 200:
        status = resp.status_code if resp is not None else "no response"
        raise LLMError(f"gemini returned {status}")
    return payload, model, latency_ms


_KEY = re.compile(r',\s*"[A-Za-z_]+"\s*:')


def _closers(prefix: str) -> str:
    """The brackets that close every object/array still open at the end of ``prefix``."""
    stack: list[str] = []
    in_string = escaped = False
    for ch in prefix:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]" and stack:
            stack.pop()
    return "".join(reversed(stack))


def _salvage(text: str, required: tuple[str, ...]) -> dict[str, Any] | None:
    """Keep the complete part of an answer cut off by the token cap.

    The usual failure is the model repeating words inside one long text field
    until the cap. Everything before that field is complete, so cut at the last
    key boundary that still parses, close whatever is open (also inside the
    grievance object, so its finished fields survive), and accept the result only
    if every required top-level field is there."""
    for match in reversed(list(_KEY.finditer(text))):
        prefix = text[: match.start()]
        try:
            data = json.loads(prefix + _closers(prefix))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and all(key in data for key in required):
            return data
    return None


def parse_json_output(payload: dict[str, Any], *, required: tuple[str, ...] = ()) -> dict[str, Any]:
    """The first candidate's answer (thinking parts skipped) as a JSON object.

    With ``required``, an answer cut off at the token cap is salvaged when all
    required fields are complete (only a trailing optional field is lost)."""
    candidates = payload.get("candidates") or []
    if not candidates:
        raise LLMError(f"gemini returned no candidates: {payload.get('promptFeedback')}")
    candidate = candidates[0]
    text = "".join(
        part.get("text", "")
        for part in candidate.get("content", {}).get("parts", [])
        if not part.get("thought")
    )
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        reason = candidate.get("finishReason")
        if reason == "MAX_TOKENS" and required:
            salvaged = _salvage(text, required)
            if salvaged is not None:
                logger.warning("gemini_output_salvaged", kept=sorted(salvaged))
                return salvaged
        usage = payload.get("usageMetadata", {})
        raise LLMError(
            f"gemini output was not valid JSON (finish={reason}, "
            f"thoughts={usage.get('thoughtsTokenCount')}, "
            f"output={usage.get('candidatesTokenCount')})"
        ) from exc
    if not isinstance(data, dict):
        raise LLMError("gemini output was not a JSON object")
    return data


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, *, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or settings.gemini_api_key
        self.model = model or settings.llm_model
        if not self.api_key:
            raise LLMError("GEMINI_API_KEY is not set")

    async def generate_json(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        schema: dict[str, Any],
        max_output_tokens: int,
    ) -> LLMResult:
        body: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [
                {"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.text}]}
                for m in messages
            ],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": max_output_tokens,
                "responseMimeType": "application/json",
                "responseSchema": schema,
                "thinkingConfig": {"thinkingLevel": settings.llm_thinking_level},
            },
        }
        chain = model_chain(self.model)
        required = tuple(schema.get("required", []))
        payload, model, latency_ms = await call_gemini(
            api_key=self.api_key, models=chain, body=body
        )
        try:
            data = parse_json_output(payload, required=required)
        except LLMError as exc:
            # Broken output (usually one field repeating until the token cap) is rare
            # and random, so one fresh try, on the fallback model when there is one,
            # nearly always works. Slower than a good answer, better than "sorry".
            logger.warning("gemini_bad_output_retry", model=model, error=str(exc))
            payload, model, retry_ms = await call_gemini(
                api_key=self.api_key, models=chain[1:] or chain, body=body
            )
            latency_ms += retry_ms
            data = parse_json_output(payload, required=required)
        usage = payload.get("usageMetadata", {})
        return LLMResult(
            data=data,
            model=model,
            prompt_tokens=usage.get("promptTokenCount"),
            completion_tokens=(usage.get("candidatesTokenCount") or 0)
            + (usage.get("thoughtsTokenCount") or 0),
            latency_ms=latency_ms,
            raw=payload,
        )
