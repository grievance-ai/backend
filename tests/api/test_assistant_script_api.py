"""The assistant retries once when a reply uses the wrong Indian script."""

import secrets
from typing import Any

from app.integrations.llm import mock
from httpx import AsyncClient

NS = "/api/v2/xuanwu"
SEND = f"{NS}/resource/conversations/messages"


def _answer(reply: str) -> dict[str, Any]:
    return {
        "mode": "scheme_enquiry",
        "answer_status": "answered",
        "reply": reply,
        "schemes": [],
        "follow_ups": [],
        "facts": [],
    }


async def _ask(client: AsyncClient, language: str = "pa") -> str:
    mobile = "9" + "".join(secrets.choice("0123456789") for _ in range(9))
    login = await client.post(
        f"{NS}/identity/sessions/mobile", json={"mobile": mobile, "otp": "1111"}
    )
    headers = {"X-CSRF-Token": login.json()["data"]["csrf_token"]}
    resp = await client.post(
        SEND, json={"text": "ਮੈਂ ਕਿਹੜੀ ਸਕੀਮ ਲਈ ਯੋਗ ਹਾਂ?", "language": language}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["data"]["assistant_message"]["content"])


async def test_clean_reply_is_not_retried(client: AsyncClient) -> None:
    mock.clear()
    mock.queue_response(_answer("ਇੰਦਰਾ ਗਾਂਧੀ ਪੈਨਸ਼ਨ ਸਕੀਮ"))
    assert await _ask(client) == "ਇੰਦਰਾ ਗਾਂਧੀ ਪੈਨਸ਼ਨ ਸਕੀਮ"
    assert len(mock.calls) == 1


async def test_wrong_script_is_retried_with_a_reminder(client: AsyncClient) -> None:
    mock.clear()
    mock.queue_response(_answer("ਇందిరਾ ਗਾਂਧੀ ਪੈਨਸ਼ਨ ਸਕੀਮ"))
    mock.queue_response(_answer("ਇੰਦਰਾ ਗਾਂਧੀ ਪੈਨਸ਼ਨ ਸਕੀਮ"))
    assert await _ask(client) == "ਇੰਦਰਾ ਗਾਂਧੀ ਪੈਨਸ਼ਨ ਸਕੀਮ"
    assert len(mock.calls) == 2
    assert "Gurmukhi letters only" in mock.calls[1]["messages"][-1].text


async def test_worse_retry_keeps_the_first_reply(client: AsyncClient) -> None:
    mock.clear()
    mock.queue_response(_answer("ਇందిరਾ ਗਾਂਧੀ"))  # 4 stray letters
    mock.queue_response(_answer("ఇందిరా గాంధీ"))  # all Telugu
    assert await _ask(client) == "ਇందిరਾ ਗਾਂਧੀ"
    assert len(mock.calls) == 2
