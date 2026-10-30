"""Gemini with the Google Search tool (``generateContent``), returning grounding data."""

from typing import Any

from app.core.config import settings
from app.integrations.llm.base import LLMError
from app.integrations.llm.gemini import call_gemini, model_chain
from app.integrations.websearch.base import (
    GroundedAnswer,
    Support,
    WebPage,
    WebSearchError,
    WebSearchProvider,
)

NOT_FOUND = "NOT_FOUND"

INSTRUCTIONS = """\
You help citizens of Punjab, India find government schemes.
Search the web and answer the question using ONLY official Indian government
websites: sites whose address ends in .gov.in or .nic.in. Ignore news sites,
blogs, private portals and anything else.
Write {language} in plain text, no markdown, no URLs, at most 5 short sentences:
what the scheme gives, who can get it, and how to apply, as far as the official
pages say. Never guess or add anything an official page does not state.
If no official government page answers the question, reply exactly NOT_FOUND."""


class GeminiWebSearchProvider(WebSearchProvider):
    async def answer(self, *, question: str, language_name: str) -> GroundedAnswer:
        body: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": INSTRUCTIONS.format(language=language_name)}]},
            "contents": [{"role": "user", "parts": [{"text": question}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {"maxOutputTokens": 1024},
        }
        try:
            payload, model, latency_ms = await call_gemini(
                api_key=settings.gemini_api_key,
                models=model_chain(settings.websearch_model or settings.llm_model),
                body=body,
            )
        except LLMError as exc:
            raise WebSearchError(str(exc)) from exc
        return parse(payload, model=model, latency_ms=latency_ms)


def parse(
    payload: dict[str, Any], *, model: str | None = None, latency_ms: int | None = None
) -> GroundedAnswer:
    candidates = payload.get("candidates") or []
    if not candidates:
        raise WebSearchError("gemini returned no candidates")
    candidate = candidates[0]
    text = "".join(
        part.get("text", "")
        for part in candidate.get("content", {}).get("parts", [])
        if not part.get("thought")
    ).strip()
    meta = candidate.get("groundingMetadata") or {}
    pages = [
        WebPage(url=str(web.get("uri", "")), title=str(web.get("title", "")))
        for chunk in meta.get("groundingChunks") or []
        if (web := chunk.get("web"))
    ]
    supports = [
        Support(
            text=str(s.get("segment", {}).get("text", "")),
            pages=tuple(int(i) for i in s.get("groundingChunkIndices") or []),
        )
        for s in meta.get("groundingSupports") or []
    ]
    if text == NOT_FOUND or text.startswith(NOT_FOUND):
        text, supports = "", []
    return GroundedAnswer(
        text=text,
        pages=pages,
        supports=supports,
        queries=[str(q) for q in meta.get("webSearchQueries") or []],
        model=model,
        latency_ms=latency_ms,
    )
