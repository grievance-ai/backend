"""Citizen profile: onboarding details, language, and use by the assistant."""

import secrets
from typing import Any

import pytest_asyncio
from app.db.knowledge import seed_geography
from app.integrations.llm import mock
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

NS = "/api/v2/xuanwu"
PROFILE = f"{NS}/resource/citizen-profile"

FULL = {
    "name": "Sudhanshu Singh",
    "age": 28,
    "gender": "male",
    "marital_status": "single",
    "district_code": "LDH",
    "area_type": "rural",
    "village": "Mullanpur",
}


@pytest_asyncio.fixture(autouse=True)
async def _districts(db: AsyncSession) -> None:
    await seed_geography(db)  # idempotent


def _mobile() -> str:
    return "9" + "".join(secrets.choice("0123456789") for _ in range(9))


async def _login(client: AsyncClient, mobile: str, language: str = "pa") -> dict[str, Any]:
    resp = await client.post(
        f"{NS}/identity/sessions/mobile",
        json={"mobile": mobile, "otp": "1111", "language": language},
    )
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json()["data"]
    return data


async def test_new_citizen_starts_incomplete(client: AsyncClient) -> None:
    session = await _login(client, _mobile())
    assert session["profile_complete"] is False

    resp = await client.get(f"{PROFILE}/me")
    profile = resp.json()["data"]
    assert profile["is_complete"] is False
    assert profile["preferred_language"] == "pa"
    assert profile["name"] is None


async def test_full_profile_is_saved_and_marks_complete(client: AsyncClient) -> None:
    mobile = _mobile()
    session = await _login(client, mobile)
    resp = await client.patch(PROFILE, json=FULL, headers={"X-CSRF-Token": session["csrf_token"]})

    assert resp.status_code == 200, resp.text
    profile = resp.json()["data"]
    assert profile["name"] == "Sudhanshu Singh"
    assert profile["age"] == 28
    assert profile["gender"] == "male"
    assert profile["marital_status"] == "single"
    assert profile["district"] == {"code": "LDH", "name_en": "Ludhiana", "name_pa": "ਲੁਧਿਆਣਾ"}
    assert profile["area_type"] == "rural"
    assert profile["village"] == "Mullanpur"
    assert profile["is_complete"] is True

    # Next login knows the profile is done, so onboarding is skipped.
    assert (await _login(client, mobile))["profile_complete"] is True


async def test_partial_update_only_changes_sent_fields(client: AsyncClient) -> None:
    session = await _login(client, _mobile(), language="pa")
    headers = {"X-CSRF-Token": session["csrf_token"]}
    await client.patch(PROFILE, json=FULL, headers=headers)

    resp = await client.patch(PROFILE, json={"preferred_language": "en"}, headers=headers)
    profile = resp.json()["data"]
    assert profile["preferred_language"] == "en"
    assert profile["name"] == "Sudhanshu Singh"
    assert profile["district"]["code"] == "LDH"


async def test_rejects_unknown_district_and_bad_values(client: AsyncClient) -> None:
    session = await _login(client, _mobile())
    headers = {"X-CSRF-Token": session["csrf_token"]}
    bad_district = await client.patch(PROFILE, json={"district_code": "XXX"}, headers=headers)
    assert bad_district.status_code == 422
    assert bad_district.json()["errors"] == ["resource.profile.invalid_district"]

    for body in ({"age": 0}, {"age": 200}, {"gender": "robot"}, {"marital_status": "maybe"}):
        resp = await client.patch(PROFILE, json=body, headers=headers)
        assert resp.status_code == 422, body


async def test_districts_list(client: AsyncClient) -> None:
    await _login(client, _mobile())
    resp = await client.get(f"{NS}/resource/districts")
    codes = [d["code"] for d in resp.json()["data"]]
    assert len(codes) >= 23 and "LDH" in codes and "ASR" in codes


async def test_assistant_receives_the_profile(client: AsyncClient) -> None:
    session = await _login(client, _mobile())
    headers = {"X-CSRF-Token": session["csrf_token"]}
    await client.patch(PROFILE, json={**FULL, "marital_status": "widowed"}, headers=headers)

    await client.post(
        f"{NS}/resource/conversations/messages",
        json={"text": "Any pension for me?", "language": "pa"},
        headers=headers,
    )
    context = mock.calls[-1]["messages"][0].text
    assert '"marital_status": "widowed"' in context
    assert '"area": "rural"' in context
    assert '"district": "Ludhiana"' in context
    assert '"age": 28' in context
    assert "Punjabi" in mock.calls[-1]["system"]


async def test_onboarding_without_location_is_complete(client: AsyncClient) -> None:
    """District, area type and village are optional; onboarding no longer asks for them."""
    session = await _login(client, _mobile())
    resp = await client.patch(
        PROFILE,
        json={
            "name": "Test Citizen",
            "age": 45,
            "gender": "female",
            "marital_status": "married",
            "preferred_language": "pa",
        },
        headers={"X-CSRF-Token": session["csrf_token"]},
    )
    assert resp.status_code == 200, resp.text
    profile = resp.json()["data"]
    assert profile["district"] is None
    assert profile["is_complete"] is True
