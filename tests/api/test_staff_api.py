"""Officer queue, grievance handling and the administrator overview (spec §5.9, §5.10, §10)."""

import secrets
import uuid
from typing import Any

import pytest_asyncio
from app.db.demo_staff import seed_demo_staff
from app.db.knowledge import seed_geography, seed_grievance_categories, seed_knowledge
from app.integrations.llm import mock
from app.models.conversation import ConversationMessage, MessageScheme
from app.models.scheme import Scheme
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

NS = "/api/v2/xuanwu"
R = f"{NS}/resource"
STAFF = f"{R}/staff"


@pytest_asyncio.fixture(autouse=True)
async def _reference_data(db: AsyncSession) -> None:
    await seed_geography(db)
    await seed_grievance_categories(db)


def _mobile() -> str:
    return "9" + "".join(secrets.choice("0123456789") for _ in range(9))


async def _login(client: AsyncClient, mobile: str) -> dict[str, str]:
    client.cookies.clear()
    resp = await client.post(
        f"{NS}/identity/sessions/mobile", json={"mobile": mobile, "otp": "1111"}
    )
    assert resp.status_code == 200, resp.text
    return {"X-CSRF-Token": resp.json()["data"]["csrf_token"]}


async def _staff(db: AsyncSession, client: AsyncClient, **row: Any) -> dict[str, str]:
    mobile = _mobile()
    await seed_demo_staff(db, {"staff": [{"mobile": mobile, "name": "Test Staff", **row}]})
    return await _login(client, mobile)


async def _citizen(client: AsyncClient) -> dict[str, str]:
    headers = await _login(client, _mobile())
    await client.patch(
        f"{R}/citizen-profile",
        json={"name": "Test Citizen", "district_code": "LDH"},
        headers=headers,
    )
    return headers


async def _file(client: AsyncClient, headers: dict[str, str], **overrides: Any) -> str:
    payload = {
        "category_code": "WATER",
        "subcategory_code": "WATER_NO_SUPPLY",
        "district_code": "LDH",
        "summary": "No water supply",
        "description": "No water in our street for two weeks now.",
        **overrides,
    }
    resp = await client.post(f"{R}/grievances", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return str(resp.json()["data"]["reference_no"])


async def test_citizens_cannot_use_staff_routes(client: AsyncClient) -> None:
    headers = await _citizen(client)
    ref = await _file(client, headers)
    assert (await client.get(f"{STAFF}/me")).status_code == 403
    assert (await client.get(f"{STAFF}/grievances")).status_code == 403
    assert (await client.get(f"{STAFF}/grievances/{ref}")).status_code == 403
    assert (await client.get(f"{STAFF}/overview")).status_code == 403
    resp = await client.post(
        f"{STAFF}/grievances/{ref}/status", json={"status": "closed"}, headers=headers
    )
    assert resp.status_code == 403


async def test_officer_sees_only_their_district(db: AsyncSession, client: AsyncClient) -> None:
    citizen = await _citizen(client)
    ludhiana = await _file(client, citizen)
    amritsar = await _file(client, citizen, district_code="ASR")

    await _staff(db, client, role="officer", scope_level="district", district="LDH")
    me = (await client.get(f"{STAFF}/me")).json()["data"]
    assert me["district"]["code"] == "LDH"
    assert me["can_view_overview"] is False

    queue = (await client.get(f"{STAFF}/grievances", params={"q": ludhiana})).json()["data"]
    assert [g["reference_no"] for g in queue["items"]] == [ludhiana]
    assert (await client.get(f"{STAFF}/grievances", params={"q": amritsar})).json()["data"][
        "total"
    ] == 0
    # Outside the jurisdiction looks the same as not existing.
    assert (await client.get(f"{STAFF}/grievances/{amritsar}")).status_code == 404


async def test_department_narrows_the_queue(db: AsyncSession, client: AsyncClient) -> None:
    citizen = await _citizen(client)
    water = await _file(client, citizen, district_code="ASR")
    other = await _file(
        client,
        citizen,
        district_code="ASR",
        category_code="ELECTRICITY",
        subcategory_code=None,
    )
    await _staff(
        db, client, role="officer", scope_level="district", district="ASR", department="PB_WSS"
    )
    assert (await client.get(f"{STAFF}/grievances/{water}")).status_code == 200
    assert (await client.get(f"{STAFF}/grievances/{other}")).status_code == 404


async def test_officer_reads_transcript_and_moves_status(
    db: AsyncSession, client: AsyncClient
) -> None:
    """Scene four: open the new grievance, read the transcript, move to under verification."""
    citizen_mobile = _mobile()
    citizen = await _login(client, citizen_mobile)
    await client.patch(f"{R}/citizen-profile", json={"name": "Test Citizen"}, headers=citizen)
    mock.queue_response(
        {
            "mode": "grievance_intake",
            "answer_status": "answered",
            "reply": "Please review and confirm.",
            "schemes": [],
            "follow_ups": [],
            "facts": [],
            "grievance": {"category_code": "WATER", "ready_to_confirm": True},
        }
    )
    chat = await client.post(
        f"{R}/conversations/messages",
        json={"text": "Our water supply is cut", "language": "en"},
        headers=citizen,
    )
    conversation_id = chat.json()["data"]["conversation_id"]
    ref = await _file(client, citizen, conversation_id=conversation_id)

    officer = await _staff(db, client, role="officer", scope_level="district", district="LDH")
    detail = (await client.get(f"{STAFF}/grievances/{ref}")).json()["data"]
    assert detail["status"] == "new"
    assert detail["citizen"]["name"] == "Test Citizen"
    assert [m["role"] for m in detail["transcript"]] == ["citizen", "assistant"]
    assert detail["transcript"][0]["content"] == "Our water supply is cut"
    assert "under_verification" in detail["next_statuses"]

    bad = await client.post(
        f"{STAFF}/grievances/{ref}/status", json={"status": "resolved"}, headers=officer
    )
    assert bad.status_code == 422  # new → resolved skips verification

    resp = await client.post(
        f"{STAFF}/grievances/{ref}/status",
        json={"status": "under_verification", "remark": "Field visit tomorrow"},
        headers=officer,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["status"] == "under_verification"
    assert data["assigned_officer"] == "Test Staff"  # the officer took it
    assert [h["event_type"] for h in data["history"]] == [
        "status_change",
        "assignment",
        "status_change",
    ]

    no_remark = await client.post(
        f"{STAFF}/grievances/{ref}/status", json={"status": "resolved"}, headers=officer
    )
    assert no_remark.status_code == 422
    assert no_remark.json()["errors"] == ["resource.grievance.remark_required"]

    # The citizen sees the new status.
    await _login(client, citizen_mobile)
    mine = (await client.get(f"{R}/grievances/{ref}")).json()["data"]
    assert mine["status"] == "under_verification"


async def test_internal_notes_stay_internal(db: AsyncSession, client: AsyncClient) -> None:
    citizen_mobile = _mobile()
    citizen = await _login(client, citizen_mobile)
    await client.patch(f"{R}/citizen-profile", json={"name": "N"}, headers=citizen)
    ref = await _file(client, citizen)

    officer = await _staff(db, client, role="officer", scope_level="district", district="LDH")
    for visibility, text in (("internal", "Call the JE first"), ("citizen", "Team assigned")):
        resp = await client.post(
            f"{STAFF}/grievances/{ref}/notes",
            json={"content": text, "visibility": visibility},
            headers=officer,
        )
        assert resp.status_code == 200, resp.text
    assert len(resp.json()["data"]["notes"]) == 2

    await _login(client, citizen_mobile)
    mine = (await client.get(f"{R}/grievances/{ref}")).json()["data"]
    assert [u["content"] for u in mine["updates"]] == ["Team assigned"]


async def test_overview_is_for_administrators(db: AsyncSession, client: AsyncClient) -> None:
    """Scene five: grievances by category and district, and most-asked schemes."""
    await _staff(db, client, role="officer", scope_level="district", district="LDH")
    assert (await client.get(f"{STAFF}/overview")).status_code == 403

    await _staff(db, client, role="admin", scope_level="state")
    before = (await client.get(f"{STAFF}/overview")).json()["data"]

    citizen = await _citizen(client)
    await _file(client, citizen, district_code="MNS")

    # One assistant answer that covered a scheme.
    await seed_knowledge(db)
    scheme = (await db.scalars(select(Scheme).limit(1))).one()
    scheme_id, slug = scheme.id, scheme.slug
    await db.commit()  # end this snapshot so the chat's rows are visible below
    mock.queue_response(
        {
            "mode": "scheme_enquiry",
            "answer_status": "answered",
            "reply": "Here is what I found.",
            "schemes": [],
            "follow_ups": [],
            "facts": [],
        }
    )
    chat = await client.post(
        f"{R}/conversations/messages",
        json={"text": "Which schemes for farmers?", "language": "en"},
        headers=citizen,
    )
    message_id = chat.json()["data"]["assistant_message"]["id"]
    await db.commit()
    answer = await db.scalar(
        select(ConversationMessage).where(ConversationMessage.id == uuid.UUID(message_id))
    )
    assert answer is not None
    db.add(MessageScheme(message_id=answer.id, scheme_id=scheme_id))
    await db.commit()

    await _staff(db, client, role="admin", scope_level="state")
    resp = await client.get(f"{STAFF}/overview", params={"days": 7})
    assert resp.status_code == 200, resp.text
    after = resp.json()["data"]

    def count(rows: list[dict[str, Any]], code: str) -> int:
        return next((r["count"] for r in rows if r["code"] == code), 0)

    assert after["totals"]["grievances"] == before["totals"]["grievances"] + 1
    assert count(after["by_district"], "MNS") == count(before["by_district"], "MNS") + 1
    assert count(after["by_category"], "WATER") == count(before["by_category"], "WATER") + 1
    assert count(after["top_schemes"], slug) >= 1
    assert len(after["daily"]) == 14
    assert after["daily"][-1]["grievances"] >= 1


async def test_district_admin_overview_is_scoped(db: AsyncSession, client: AsyncClient) -> None:
    citizen = await _citizen(client)
    await _file(client, citizen, district_code="FDK")
    await _staff(db, client, role="admin", scope_level="district", district="LDH")
    data = (await client.get(f"{STAFF}/overview")).json()["data"]
    assert {r["code"] for r in data["by_district"]} <= {"LDH"}


async def test_queue_filters_by_department_and_counts_overdue(
    db: AsyncSession, client: AsyncClient
) -> None:
    citizen = await _citizen(client)
    water = await _file(client, citizen, district_code="BTI")
    power = await _file(
        client, citizen, district_code="BTI", category_code="ELECTRICITY", subcategory_code=None
    )
    await _staff(db, client, role="admin", scope_level="district", district="BTI")

    queue = (await client.get(f"{STAFF}/grievances", params={"department": "PB_WSS"})).json()
    refs = [g["reference_no"] for g in queue["data"]["items"]]
    assert water in refs and power not in refs
    assert queue["data"]["overdue_count"] >= 0

    codes = [d["code"] for d in (await client.get(f"{STAFF}/departments")).json()["data"]]
    assert "PB_WSS" in codes and "PSPCL" in codes
    assert "AGRICULTURE" not in codes  # scheme ministries are not grievance departments

    # An officer tied to one department only gets that one.
    await _staff(
        db, client, role="officer", scope_level="district", district="BTI", department="PB_WSS"
    )
    codes = [d["code"] for d in (await client.get(f"{STAFF}/departments")).json()["data"]]
    assert codes == ["PB_WSS"]


async def test_overview_trend_comparison_and_filters(db: AsyncSession, client: AsyncClient) -> None:
    # The test database is shared and never reset: compare before and after.
    params: dict[str, str | int] = {"days": 7, "district": "KPT"}
    water: dict[str, str | int] = {**params, "department": "PB_WSS"}
    await _staff(db, client, role="admin", scope_level="state")
    before = (await client.get(f"{STAFF}/overview", params=params)).json()["data"]
    before_water = (await client.get(f"{STAFF}/overview", params=water)).json()["data"]

    citizen = await _citizen(client)
    ref = await _file(client, citizen, district_code="KPT")
    await _file(
        client, citizen, district_code="KPT", category_code="ELECTRICITY", subcategory_code=None
    )
    headers = await _staff(db, client, role="admin", scope_level="state")
    resp = await client.post(
        f"{STAFF}/grievances/{ref}/status",
        json={"status": "closed", "remark": "Fixed.", "resolution_outcome": "resolved_fully"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    after = (await client.get(f"{STAFF}/overview", params=params)).json()["data"]
    assert len(after["trend"]) == 7
    assert after["trend"][-1]["new"] == before["trend"][-1]["new"] + 2
    assert after["trend"][-1]["resolved"] == before["trend"][-1]["resolved"] + 1
    reg, res = after["comparison"]["registered"], after["comparison"]["resolved"]
    assert reg["current"] == before["comparison"]["registered"]["current"] + 2
    assert res["current"] == before["comparison"]["resolved"]["current"] + 1
    assert {r["code"] for r in after["by_district"]} == {"KPT"}

    after_water = (await client.get(f"{STAFF}/overview", params=water)).json()["data"]
    registered = after_water["comparison"]["registered"]["current"]
    assert registered == before_water["comparison"]["registered"]["current"] + 1
    assert [r["code"] for r in after_water["by_department"]] == ["PB_WSS"]
