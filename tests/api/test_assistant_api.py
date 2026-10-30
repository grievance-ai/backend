"""Citizen assistant: grounding, persistence and access rules."""

import secrets
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from app.integrations.llm import mock
from app.integrations.llm.base import LLMError
from app.models.conversation import ConversationMessage, MessageScheme, UnansweredQuestion
from app.models.scheme import Scheme, SchemeEligibilityCondition
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

NS = "/api/v2/xuanwu"
SEND = f"{NS}/resource/conversations/messages"


@pytest_asyncio.fixture
async def scheme(db: AsyncSession) -> AsyncIterator[Scheme]:
    """A throwaway scheme, deleted afterwards so it never leaks into the dev
    knowledge base (the test database is shared and not reset)."""
    row = Scheme(
        slug=f"test-scheme-{uuid.uuid4().hex[:8]}",
        name="Test Housing Scheme",
        short_name="THS",
        description="Housing help.",
        benefits="Rs 1 lakh.",
        required_documents=["Aadhaar card"],
        application_steps=["Visit the block office."],
        official_url="https://example.gov.in/ths",
        conditions=[
            SchemeEligibilityCondition(
                field_name="owns_pucca_house",
                operator="eq",
                value=False,
                description="No pucca house.",
            )
        ],
    )
    db.add(row)
    await db.commit()
    yield row
    await db.execute(delete(MessageScheme).where(MessageScheme.scheme_id == row.id))
    await db.execute(delete(Scheme).where(Scheme.id == row.id))
    await db.commit()


async def _citizen(client: AsyncClient) -> str:
    mobile = "9" + "".join(secrets.choice("0123456789") for _ in range(9))
    resp = await client.post(
        f"{NS}/identity/sessions/mobile", json={"mobile": mobile, "otp": "1111"}
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["data"]["csrf_token"])


def _answer(slug: str, **overrides: Any) -> dict[str, Any]:
    card = {
        "slug": slug,
        "eligible": "unknown",
        "summary": "Helps families build a house.",
        "benefit": "Rs 1 lakh.",
        "conditions": [{"text": "No pucca house.", "status": "unknown"}],
        "documents": ["Aadhaar card"],
        "steps": ["Visit the block office."],
    }
    return {
        "mode": "scheme_enquiry",
        "answer_status": "answered",
        "reply": "Here is what applies.",
        "schemes": [card],
        "follow_ups": ["Show documents"],
        "facts": [{"key": "area", "value": "rural"}],
        **overrides,
    }


async def test_requires_login(client: AsyncClient) -> None:
    resp = await client.post(SEND, json={"text": "hello", "language": "en"})
    assert resp.status_code == 401


async def test_requires_csrf(client: AsyncClient) -> None:
    await _citizen(client)
    resp = await client.post(SEND, json={"text": "hello", "language": "en"})
    assert resp.status_code == 403


async def test_answer_is_grounded_in_the_database(
    client: AsyncClient, db: AsyncSession, scheme: Scheme
) -> None:
    csrf = await _citizen(client)
    answer = _answer(scheme.slug)
    # The model also names a scheme that does not exist: it must be dropped.
    answer["schemes"].append({**answer["schemes"][0], "slug": "made-up-scheme"})
    mock.queue_response(answer)

    resp = await client.post(
        SEND,
        json={"text": "Housing help?", "language": "en"},
        headers={"X-CSRF-Token": csrf},
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["mode"] == "scheme_enquiry"
    cards = data["assistant_message"]["schemes"]
    assert [c["slug"] for c in cards] == [scheme.slug]
    assert cards[0]["official_url"] == "https://example.gov.in/ths"  # from the DB
    assert cards[0]["name"] == "Test Housing Scheme"
    assert data["assistant_message"]["follow_ups"] == ["Show documents"]

    # The system prompt carried the scheme data and the reply language.
    call = mock.calls[-1]
    assert "English" in call["system"]
    assert scheme.slug in call["messages"][0].text

    mentions = await db.scalars(select(MessageScheme).where(MessageScheme.scheme_id == scheme.id))
    assert len(mentions.all()) == 1


async def test_conversation_continues_and_keeps_facts(client: AsyncClient, scheme: Scheme) -> None:
    csrf = await _citizen(client)
    headers = {"X-CSRF-Token": csrf}
    mock.queue_response(_answer(scheme.slug))
    first = await client.post(SEND, json={"text": "Housing?", "language": "pa"}, headers=headers)
    conversation_id = first.json()["data"]["conversation_id"]

    mock.queue_response(_answer(scheme.slug))
    second = await client.post(
        SEND,
        json={"text": "Documents?", "language": "pa", "conversation_id": conversation_id},
        headers=headers,
    )
    assert second.json()["data"]["conversation_id"] == conversation_id
    # The second prompt includes the fact learned in the first turn and the history.
    context = mock.calls[-1]["messages"][0].text
    assert '"area": "rural"' in context
    assert any(m.text == "Housing?" for m in mock.calls[-1]["messages"])
    # The newest message carries the reply-language reminder.
    assert mock.calls[-1]["messages"][-1].text.startswith("Documents?")
    assert "Punjabi" in mock.calls[-1]["messages"][-1].text

    detail = await client.get(f"{NS}/resource/conversations/{conversation_id}")
    roles = [m["role"] for m in detail.json()["data"]["messages"]]
    assert roles == ["citizen", "assistant", "citizen", "assistant"]


async def test_unanswerable_question_is_logged(client: AsyncClient, db: AsyncSession) -> None:
    csrf = await _citizen(client)
    mock.queue_response(
        {
            "mode": "scheme_enquiry",
            "answer_status": "not_in_data",
            "reply": "I don't have that information.",
            "schemes": [],
            "follow_ups": [],
            "facts": [],
        }
    )
    question = f"Unknown scheme {uuid.uuid4().hex[:6]}?"
    resp = await client.post(
        SEND, json={"text": question, "language": "en"}, headers={"X-CSRF-Token": csrf}
    )
    assert resp.json()["data"]["assistant_message"]["answer_status"] == "not_in_data"
    logged = await db.scalar(
        select(UnansweredQuestion).where(UnansweredQuestion.question == question)
    )
    assert logged is not None


async def test_llm_failure_returns_a_polite_fallback(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise LLMError("quota exceeded")

    monkeypatch.setattr(mock.MockLLMProvider, "generate_json", boom)
    csrf = await _citizen(client)
    resp = await client.post(
        SEND, json={"text": "Hello", "language": "pa"}, headers={"X-CSRF-Token": csrf}
    )
    assert resp.status_code == 200
    message = resp.json()["data"]["assistant_message"]
    assert message["content"].startswith("ਮਾਫ਼ ਕਰਨਾ")
    assert message["schemes"] == []
    saved = await db.get(ConversationMessage, uuid.UUID(message["id"]))
    assert saved is not None and saved.llm_model is None


async def test_cannot_read_another_citizens_conversation(client: AsyncClient) -> None:
    csrf = await _citizen(client)
    mock.queue_response(_answer("none"))
    turn = await client.post(
        SEND, json={"text": "Hi", "language": "en"}, headers={"X-CSRF-Token": csrf}
    )
    conversation_id = turn.json()["data"]["conversation_id"]

    await _citizen(client)  # log in as someone else (cookies replaced)
    resp = await client.get(f"{NS}/resource/conversations/{conversation_id}")
    assert resp.status_code == 404
