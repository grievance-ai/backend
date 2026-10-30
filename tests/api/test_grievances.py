"""Grievance intake → review → submit → track (spec §5.8)."""

import datetime as dt
import re
import secrets
from typing import Any

import pytest_asyncio
from app.db.knowledge import seed_geography, seed_grievance_categories
from app.integrations.llm import mock
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

NS = "/api/v2/xuanwu"
R = f"{NS}/resource"
REF = re.compile(r"^GRV-\d{4}-\d{6}$")


@pytest_asyncio.fixture(autouse=True)
async def _reference_data(db: AsyncSession) -> None:
    await seed_geography(db)
    await seed_grievance_categories(db)


async def _citizen(client: AsyncClient) -> dict[str, str]:
    mobile = "9" + "".join(secrets.choice("0123456789") for _ in range(9))
    resp = await client.post(
        f"{NS}/identity/sessions/mobile", json={"mobile": mobile, "otp": "1111"}
    )
    headers = {"X-CSRF-Token": resp.json()["data"]["csrf_token"]}
    await client.patch(
        f"{R}/citizen-profile",
        json={"name": "Test Citizen", "district_code": "LDH", "area_type": "urban"},
        headers=headers,
    )
    return headers


def _intake(ready: bool, **grievance: Any) -> dict[str, Any]:
    return {
        "mode": "grievance_intake",
        "answer_status": "answered",
        "reply": "Please review and confirm." if ready else "Since when?",
        "schemes": [],
        "follow_ups": [],
        "facts": [],
        "grievance": {
            "category_code": "WATER",
            "subcategory_code": "WATER_NO_SUPPLY",
            "summary": "No water supply for two weeks",
            "district": "ਲੁਧਿਆਣਾ",
            "location": "Ward 12, Model Town",
            "description": "There has been no water supply in our street for two weeks.",
            "since": "two weeks",
            "prior_complaint": "Told the local office, no action",
            "ready_to_confirm": ready,
            **grievance,
        },
    }


async def _chat(client: AsyncClient, headers: dict[str, str], reply: dict[str, Any]) -> Any:
    mock.queue_response(reply)
    resp = await client.post(
        f"{R}/conversations/messages",
        json={"text": "Our water supply is cut", "language": "pa"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _payload(**overrides: Any) -> dict[str, Any]:
    return {
        "category_code": "WATER",
        "subcategory_code": "WATER_NO_SUPPLY",
        "district_code": "LDH",
        "location_detail": "Ward 12",
        "summary": "No water supply",
        "description": "No water in our street for two weeks now.",
        **overrides,
    }


async def test_categories_have_departments_and_subcategories(client: AsyncClient) -> None:
    await _citizen(client)
    data = (await client.get(f"{R}/grievance-categories")).json()["data"]
    water = next(c for c in data if c["code"] == "WATER")
    assert water["department"]["code"] == "PB_WSS"
    assert water["name_pa"] == "ਪਾਣੀ ਦੀ ਸਪਲਾਈ"
    assert "WATER_NO_SUPPLY" in [s["code"] for s in water["subcategories"]]


async def test_assistant_builds_a_draft_and_flags_it_ready(client: AsyncClient) -> None:
    headers = await _citizen(client)

    first = await _chat(client, headers, _intake(ready=False, subcategory_code="MADE_UP"))
    assert first["mode"] == "grievance_intake"
    assert first["assistant_message"]["grievance_ready"] is False
    # The prompt offered the category list to choose from.
    assert '"code": "WATER"' in mock.calls[-1]["messages"][0].text

    second = await _chat(client, headers, _intake(ready=True))
    assert second["assistant_message"]["grievance_ready"] is True

    draft = (
        await client.get(
            f"{R}/grievances/draft", params={"conversation_id": second["conversation_id"]}
        )
    ).json()["data"]
    assert draft["category_code"] == "WATER"
    assert draft["subcategory_code"] == "WATER_NO_SUPPLY"
    assert draft["district_code"] == "LDH"  # matched from the Punjabi name
    assert draft["location_detail"] == "Ward 12, Model Town"
    assert draft["since"] == "two weeks"


async def test_degenerate_draft_fields_are_dropped(client: AsyncClient) -> None:
    """A model reply that dumps junk into one field must not reach the review screen."""
    headers = await _citizen(client)
    junk = "Streetlights broken. " * 30  # ~630 chars, far beyond a one-line summary
    data = await _chat(client, headers, _intake(ready=True, summary=junk, description=""))
    assert data["assistant_message"]["grievance_ready"] is False
    draft = (
        await client.get(
            f"{R}/grievances/draft", params={"conversation_id": data["conversation_id"]}
        )
    ).json()["data"]
    assert draft["summary"] != junk


async def test_submit_from_conversation(client: AsyncClient) -> None:
    headers = await _citizen(client)
    turn = await _chat(client, headers, _intake(ready=True))
    conversation_id = turn["conversation_id"]

    resp = await client.post(
        f"{R}/grievances",
        json=_payload(conversation_id=conversation_id, since="two weeks"),
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    g = resp.json()["data"]
    assert REF.match(g["reference_no"])
    assert g["status"] == "new"
    assert g["department"]["code"] == "PB_WSS"
    assert g["district"]["code"] == "LDH"
    assert g["since"] == "two weeks"
    assert [h["to_status"] for h in g["history"]] == ["new"]
    submitted = dt.datetime.fromisoformat(g["submitted_at"])
    due = dt.datetime.fromisoformat(g["due_at"])
    assert (due - submitted).days == 7  # WATER SLA

    # Tapping "Register" twice must not file two grievances.
    again = await client.post(
        f"{R}/grievances", json=_payload(conversation_id=conversation_id), headers=headers
    )
    assert again.json()["data"]["reference_no"] == g["reference_no"]

    mine = (await client.get(f"{R}/grievances")).json()["data"]
    assert [m["reference_no"] for m in mine].count(g["reference_no"]) == 1


async def test_references_increase_and_repeat_is_flagged(client: AsyncClient) -> None:
    headers = await _citizen(client)
    first = (await client.post(f"{R}/grievances", json=_payload(), headers=headers)).json()["data"]
    second = (await client.post(f"{R}/grievances", json=_payload(), headers=headers)).json()["data"]

    assert int(second["reference_no"][-6:]) > int(first["reference_no"][-6:])
    assert first["possible_duplicate_of"] is None
    assert second["possible_duplicate_of"] == first["reference_no"]  # flagged, not merged
    assert second["status"] == "new"


async def test_validation(client: AsyncClient) -> None:
    headers = await _citizen(client)
    cases = [
        (_payload(category_code="NOPE"), "resource.grievance.invalid_category"),
        (_payload(category_code="WATER_NO_SUPPLY"), "resource.grievance.invalid_category"),
        (_payload(subcategory_code="POWER_CUT"), "resource.grievance.invalid_subcategory"),
        (_payload(district_code="XXX"), "resource.grievance.invalid_district"),
    ]
    for body, error in cases:
        resp = await client.post(f"{R}/grievances", json=body, headers=headers)
        assert resp.status_code == 422, body
        assert resp.json()["errors"] == [error]
    short = await client.post(
        f"{R}/grievances", json=_payload(description="short"), headers=headers
    )
    assert short.status_code == 422


async def test_citizens_only_see_their_own(client: AsyncClient) -> None:
    headers = await _citizen(client)
    ref = (await client.post(f"{R}/grievances", json=_payload(), headers=headers)).json()["data"][
        "reference_no"
    ]
    assert (await client.get(f"{R}/grievances/{ref}")).status_code == 200

    await _citizen(client)  # someone else logs in
    assert (await client.get(f"{R}/grievances/{ref}")).status_code == 404
    assert ref not in [
        g["reference_no"] for g in (await client.get(f"{R}/grievances")).json()["data"]
    ]


async def test_blank_fields_never_erase_earlier_details(client: AsyncClient) -> None:
    """The model returns every grievance field, with "" for unknowns. A later turn
    with blanks must keep what earlier turns collected, and a summary alone is
    enough description to open the review screen."""
    headers = await _citizen(client)

    async def turn(reply: dict[str, Any], conversation_id: str | None) -> Any:
        mock.queue_response(reply)
        resp = await client.post(
            f"{R}/conversations/messages",
            json={"text": "Power cut", "language": "en", "conversation_id": conversation_id},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["data"]

    first = await turn(
        _intake(ready=False, location="Sector 78", since="yesterday", description=""), None
    )
    blanks = {k: "" for k in ("district", "location", "since", "prior_complaint", "description")}
    second = await turn(
        _intake(ready=True, summary="No water in Sector 78", **blanks), first["conversation_id"]
    )

    assert second["assistant_message"]["grievance_ready"] is True
    draft = (
        await client.get(
            f"{R}/grievances/draft", params={"conversation_id": second["conversation_id"]}
        )
    ).json()["data"]
    assert draft["location_detail"] == "Sector 78"
    assert draft["since"] == "yesterday"
    assert draft["summary"] == "No water in Sector 78"
    assert draft["description"] == "No water in Sector 78"  # summary stands in
