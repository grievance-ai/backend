"""Official-website fallback in the chat: pending reply, search, result message."""

import secrets
import uuid
from typing import Any

import pytest
from app.core.config import settings
from app.integrations.llm import mock
from app.integrations.websearch import GroundedAnswer, Support, WebPage, WebSearchError
from app.integrations.websearch import mock as web
from httpx import AsyncClient

NS = "/api/v2/xuanwu"
SEND = f"{NS}/resource/conversations/messages"


async def _citizen(client: AsyncClient) -> dict[str, str]:
    client.cookies.clear()
    mobile = "9" + "".join(secrets.choice("0123456789") for _ in range(9))
    resp = await client.post(
        f"{NS}/identity/sessions/mobile", json={"mobile": mobile, "otp": "1111"}
    )
    assert resp.status_code == 200, resp.text
    return {"X-CSRF-Token": resp.json()["data"]["csrf_token"]}


def _not_in_data(**overrides: Any) -> dict[str, Any]:
    return {
        "mode": "scheme_enquiry",
        "answer_status": "not_in_data",
        "reply": "That scheme is not in my verified list.",
        "schemes": [],
        "follow_ups": ["Something else"],
        "facts": [],
        **overrides,
    }


async def _ask(client: AsyncClient, headers: dict[str, str], language: str = "en") -> Any:
    """Ask about a scheme that is not in the data. The question is unique per call,
    because search results are cached per question (in a Redis shared across runs)."""
    mock.queue_response(_not_in_data())
    text = f"Tell me about the Mukh Mantri Tirth Yatra scheme {uuid.uuid4().hex[:6]}"
    resp = await client.post(SEND, json={"text": text, "language": language}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _search_url(message_id: str) -> str:
    return f"{SEND}/{message_id}/official-search"


def _grounded() -> GroundedAnswer:
    return GroundedAnswer(
        text="ignored",
        pages=[
            WebPage(url="https://punjab.gov.in/tirth-yatra", title="punjab.gov.in"),
            WebPage(url="https://blog.example.com/yatra", title="blog.example.com"),
        ],
        supports=[
            Support(text="Pilgrims travel free on the state's buses.", pages=(0,)),
            Support(text="Seats fill up fast, a blog says.", pages=(1,)),
        ],
    )


async def test_missing_scheme_reply_is_marked_for_official_search(client: AsyncClient) -> None:
    headers = await _citizen(client)
    turn = await _ask(client, headers)
    reply = turn["assistant_message"]
    assert reply["official_search"] == "pending"
    assert reply["content"].endswith("Checking official government websites now…")
    assert reply["follow_ups"] == []  # nothing to tap while the search runs


async def test_official_answer_is_added_with_official_sources_only(client: AsyncClient) -> None:
    headers = await _citizen(client)
    turn = await _ask(client, headers)
    web.queue_answer(_grounded())

    resp = await client.post(_search_url(turn["assistant_message"]["id"]), headers=headers)
    assert resp.status_code == 200, resp.text
    found = resp.json()["data"]
    assert found["role"] == "assistant"
    assert found["answer_status"] == "official_web"
    assert found["content"] == "Pilgrims travel free on the state's buses."
    assert found["web"] == {
        "found": True,
        "sources": [{"url": "https://punjab.gov.in/tirth-yatra", "title": "punjab.gov.in"}],
    }

    # Repeating the call (double tap, page reload) returns the same message.
    again = await client.post(_search_url(turn["assistant_message"]["id"]), headers=headers)
    assert again.json()["data"]["id"] == found["id"]
    assert web.MockWebSearchProvider.calls == 1

    conversation = (
        await client.get(f"{NS}/resource/conversations/{turn['conversation_id']}")
    ).json()["data"]
    messages = conversation["messages"]
    assert [m["id"] for m in messages][-1] == found["id"]
    assert messages[-2]["official_search"] == "done"


async def test_nothing_official_found(client: AsyncClient) -> None:
    headers = await _citizen(client)
    turn = await _ask(client, headers, language="pa")
    web.queue_answer(GroundedAnswer(text=""))
    resp = await client.post(_search_url(turn["assistant_message"]["id"]), headers=headers)
    data = resp.json()["data"]
    assert data["web"] == {"found": False, "sources": []}
    assert data["answer_status"] == "not_in_data"
    assert "ਸੇਵਾ ਕੇਂਦਰ" in data["content"]  # Punjabi "not found" reply


async def test_search_failure_says_so_and_is_not_cached(client: AsyncClient) -> None:
    headers = await _citizen(client)
    turn = await _ask(client, headers)
    web.queue_answer(WebSearchError("quota"))
    data = (
        await client.post(_search_url(turn["assistant_message"]["id"]), headers=headers)
    ).json()["data"]
    assert data["web"]["found"] is False
    assert "couldn't reach" in data["content"]


async def test_only_pending_replies_of_your_own_can_be_searched(client: AsyncClient) -> None:
    owner = await _citizen(client)
    turn = await _ask(client, owner)
    message_id = turn["assistant_message"]["id"]

    other = await _citizen(client)
    assert (await client.post(_search_url(message_id), headers=other)).status_code == 404

    # An ordinary answer has nothing to search.
    mock.queue_response(_not_in_data(answer_status="answered"))
    normal = (
        await client.post(SEND, json={"text": "Hello", "language": "en"}, headers=other)
    ).json()["data"]["assistant_message"]
    assert normal["official_search"] is None
    assert (await client.post(_search_url(normal["id"]), headers=other)).status_code == 409


async def test_search_can_be_switched_off(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "websearch_provider", "none")
    headers = await _citizen(client)
    reply = (await _ask(client, headers))["assistant_message"]
    assert reply["official_search"] is None
    assert reply["content"] == "That scheme is not in my verified list."
