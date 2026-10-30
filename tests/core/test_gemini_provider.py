"""Gemini provider: fallback model on overload, no fallback on real errors."""

import base64
import json
from typing import Any

import httpx
import pytest
from app.core.config import settings
from app.integrations.llm.base import LLMError, LLMMessage
from app.integrations.llm.gemini import GeminiProvider

OK_BODY = {
    "candidates": [{"content": {"parts": [{"text": json.dumps({"reply": "hi"})}]}}],
    "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 2},
}


def _patch(monkeypatch: pytest.MonkeyPatch, responses: dict[str, httpx.Response]) -> list[str]:
    called: list[str] = []

    async def fake_post(self: httpx.AsyncClient, url: str, **_kwargs: Any) -> httpx.Response:
        model = url.rsplit("/", 1)[1].split(":")[0]
        called.append(model)
        return responses[model]

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(settings, "llm_fallback_model", "lite")
    return called


async def _ask(provider: GeminiProvider) -> Any:
    return await provider.generate_json(
        system="s", messages=[LLMMessage(role="user", text="q")], schema={}, max_output_tokens=10
    )


async def test_overloaded_model_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    called = _patch(
        monkeypatch,
        {
            "main": httpx.Response(503, json={"error": {"message": "high demand"}}),
            "lite": httpx.Response(200, json=OK_BODY),
        },
    )
    result = await _ask(GeminiProvider(api_key="k", model="main"))
    assert called == ["main", "lite"]
    assert result.model == "lite"
    assert result.data == {"reply": "hi"}


async def test_bad_request_does_not_fall_back(monkeypatch: pytest.MonkeyPatch) -> None:
    called = _patch(monkeypatch, {"main": httpx.Response(400, json={"error": {"message": "bad"}})})
    with pytest.raises(LLMError):
        await _ask(GeminiProvider(api_key="k", model="main"))
    assert called == ["main"]


BROKEN_BODY = {
    "candidates": [
        {
            "finishReason": "MAX_TOKENS",
            "content": {"parts": [{"text": '{"reply": "hi", "grievance": {"summary": "$A$ $B$'}]},
        }
    ],
    "usageMetadata": {"candidatesTokenCount": 4000},
}


async def test_broken_output_is_retried_on_the_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    called = _patch(
        monkeypatch,
        {
            "main": httpx.Response(200, json=BROKEN_BODY),
            "lite": httpx.Response(200, json=OK_BODY),
        },
    )
    result = await _ask(GeminiProvider(api_key="k", model="main"))
    assert called == ["main", "lite"]
    assert result.data == {"reply": "hi"}


async def test_broken_output_twice_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    called = _patch(
        monkeypatch,
        {
            "main": httpx.Response(200, json=BROKEN_BODY),
            "lite": httpx.Response(200, json=BROKEN_BODY),
        },
    )
    with pytest.raises(LLMError):
        await _ask(GeminiProvider(api_key="k", model="main"))
    assert called == ["main", "lite"]


async def test_speech_is_sent_inline_and_read_back(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.integrations.stt.gemini import GeminiSTTProvider

    sent: list[dict[str, Any]] = []
    body = {
        "candidates": [
            {"content": {"parts": [{"text": json.dumps({"text": " ਪਾਣੀ ਨਹੀਂ ", "language": "pa"})}]}}
        ]
    }

    async def fake_post(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        sent.append(kwargs["json"])
        return httpx.Response(200, json=body)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(settings, "gemini_api_key", "k")

    result = await GeminiSTTProvider().transcribe(b"abc", mime_type="audio/webm", language="pa")

    assert result.text == "ਪਾਣੀ ਨਹੀਂ"
    assert result.language == "pa"
    inline = sent[0]["contents"][0]["parts"][1]["inlineData"]
    assert inline == {"mimeType": "audio/webm", "data": "YWJj"}


async def test_answer_cut_off_inside_the_last_field_is_salvaged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rambling = (
        '{"reply": "Noted.", "facts": [{"key": "since", "value": "a week"}], '
        '"grievance": {"summary": "No water ' + "no water " * 50
    )
    body = {
        "candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": rambling}]}}]
    }
    called = _patch(monkeypatch, {"main": httpx.Response(200, json=body)})

    result = await GeminiProvider(api_key="k", model="main").generate_json(
        system="s",
        messages=[LLMMessage(role="user", text="q")],
        schema={"required": ["reply", "facts"]},
        max_output_tokens=10,
    )

    assert called == ["main"]  # no retry needed
    assert result.data == {"reply": "Noted.", "facts": [{"key": "since", "value": "a week"}]}


async def test_cut_off_answer_missing_a_required_field_is_not_salvaged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = {
        "candidates": [
            {"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": '{"reply": "No wa'}]}}
        ]
    }
    _patch(
        monkeypatch,
        {"main": httpx.Response(200, json=body), "lite": httpx.Response(200, json=body)},
    )
    with pytest.raises(LLMError):
        await GeminiProvider(api_key="k", model="main").generate_json(
            system="s",
            messages=[LLMMessage(role="user", text="q")],
            schema={"required": ["reply"]},
            max_output_tokens=10,
        )


@pytest.mark.parametrize(
    ("text", "language"),
    [("Your complaint is noted.", "en"), ("ਤੁਹਾਡੀ ਸ਼ਿਕਾਇਤ ਦਰਜ ਹੋ ਗਈ ਹੈ।", "pa")],
)
async def test_speech_request_contains_only_the_reply(
    monkeypatch: pytest.MonkeyPatch, text: str, language: str
) -> None:
    """Instructions sent to the voice model get read aloud ("Read this in Indian
    English..."), so the request must carry the reply text and nothing else."""
    from app.integrations.tts.gemini import GeminiTTSProvider

    sent: list[dict[str, Any]] = []
    wav = base64.b64encode(b"RIFF" + b"\x00" * 40).decode()
    body = {
        "candidates": [
            {"content": {"parts": [{"inlineData": {"mimeType": "audio/wav", "data": wav}}]}}
        ]
    }

    async def fake_post(self: httpx.AsyncClient, url: str, **kwargs: Any) -> httpx.Response:
        sent.append(kwargs["json"])
        return httpx.Response(200, json=body)

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    monkeypatch.setattr(settings, "gemini_api_key", "k")

    await GeminiTTSProvider().synthesize(text, language=language)

    request = sent[0]
    assert request["contents"] == [{"role": "user", "parts": [{"text": text}]}]
    assert "systemInstruction" not in request


async def test_salvage_keeps_the_finished_fields_of_the_grievance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rambling = (
        '{"reply": "Noted.", "facts": [], "grievance": {"ready_to_confirm": true, '
        '"category_code": "ELECTRICITY", "district": "Mohali", "location": "Sector 78", '
        '"summary": "Power cut ' + "power cut " * 60
    )
    body = {
        "candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": rambling}]}}]
    }
    _patch(monkeypatch, {"main": httpx.Response(200, json=body)})

    result = await GeminiProvider(api_key="k", model="main").generate_json(
        system="s",
        messages=[LLMMessage(role="user", text="q")],
        schema={"required": ["reply", "facts"]},
        max_output_tokens=10,
    )

    assert result.data["grievance"] == {
        "ready_to_confirm": True,
        "category_code": "ELECTRICITY",
        "district": "Mohali",
        "location": "Sector 78",
    }
