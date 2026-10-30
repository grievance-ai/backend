"""Administrator Schemes page: list, detail and review status, plus the seed keeping reviews."""

import datetime as dt
import secrets
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest_asyncio
from app.db.demo_staff import seed_demo_staff
from app.db.knowledge import seed_geography, seed_knowledge
from app.models.scheme import Scheme
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

NS = "/api/v2/xuanwu"
STAFF = f"{NS}/resource/staff"
PREFIX = "test-admin-"


@pytest_asyncio.fixture(autouse=True)
async def _reference_data(db: AsyncSession) -> AsyncIterator[None]:
    """Geography in, and this file's throwaway schemes out afterwards (the test
    database is shared and never reset)."""
    await seed_geography(db)
    yield
    await db.execute(delete(Scheme).where(Scheme.slug.like(f"{PREFIX}%")))
    await db.commit()


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


def _row(slug: str, **overrides: Any) -> dict[str, Any]:
    return {
        "slug": slug,
        "name": f"Test Scheme {slug}",
        "level": "central",
        "description": "A scheme used only in tests.",
        "benefits": "Rs 100 per month.",
        "source_name": "Test source",
        "source_url": "https://example.gov.in/test",
        "conditions": [
            {"field": "age", "operator": "gte", "value": 60, "description": "You are 60+."}
        ],
        **overrides,
    }


async def _scheme(db: AsyncSession, **overrides: Any) -> str:
    slug = f"{PREFIX}{uuid.uuid4().hex[:10]}"
    await seed_knowledge(db, {"departments": [], "schemes": [_row(slug, **overrides)]})
    return slug


async def _status(db: AsyncSession, slug: str) -> tuple[str, dt.date | None]:
    db.expire_all()
    scheme = await db.scalar(select(Scheme).where(Scheme.slug == slug))
    assert scheme is not None
    return scheme.review_status, scheme.last_verified_on


async def test_only_administrators_see_schemes(db: AsyncSession, client: AsyncClient) -> None:
    slug = await _scheme(db)
    await _login(client, _mobile())  # a citizen
    assert (await client.get(f"{STAFF}/schemes")).status_code == 403
    await _staff(db, client, role="officer", scope_level="district", district="LDH")
    assert (await client.get(f"{STAFF}/schemes")).status_code == 403
    assert (await client.get(f"{STAFF}/schemes/{slug}")).status_code == 403


async def test_district_admin_can_view_but_not_review(
    db: AsyncSession, client: AsyncClient
) -> None:
    slug = await _scheme(db)
    headers = await _staff(db, client, role="admin", scope_level="district", district="LDH")

    data = (await client.get(f"{STAFF}/schemes")).json()["data"]
    assert data["can_review"] is False
    row = next(s for s in data["items"] if s["slug"] == slug)
    assert row["review_status"] == "needs_review"
    assert row["source_url"] == "https://example.gov.in/test"

    detail = (await client.get(f"{STAFF}/schemes/{slug}")).json()["data"]
    assert detail["conditions"][0]["field"] == "age"
    assert detail["can_review"] is False

    resp = await client.post(
        f"{STAFF}/schemes/{slug}/review", json={"review_status": "verified"}, headers=headers
    )
    assert resp.status_code == 403
    assert (await _status(db, slug))[0] == "needs_review"
    assert (await client.get(f"{STAFF}/schemes/no-such-scheme")).status_code == 404


async def test_state_admin_marks_a_scheme_verified(db: AsyncSession, client: AsyncClient) -> None:
    slug = await _scheme(db)
    headers = await _staff(db, client, role="admin", scope_level="state")
    before = (await client.get(f"{STAFF}/schemes")).json()["data"]["totals"]

    resp = await client.post(
        f"{STAFF}/schemes/{slug}/review",
        json={"review_status": "verified", "note": "Checked against the source"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    detail = resp.json()["data"]
    assert detail["review_status"] == "verified"
    assert detail["last_verified_on"] == dt.date.today().isoformat()
    assert detail["reviewed_by"] == "Test Staff"

    after = (await client.get(f"{STAFF}/schemes")).json()["data"]["totals"]
    assert after["verified"] == before["verified"] + 1
    assert after["needs_review"] == before["needs_review"] - 1

    resp = await client.post(
        f"{STAFF}/schemes/{slug}/review", json={"review_status": "needs_review"}, headers=headers
    )
    assert resp.json()["data"]["review_status"] == "needs_review"


async def test_seed_keeps_a_review_until_the_content_changes(db: AsyncSession) -> None:
    slug = await _scheme(db)
    scheme = await db.scalar(select(Scheme).where(Scheme.slug == slug))
    assert scheme is not None
    scheme.review_status = "verified"
    scheme.last_verified_on = dt.date(2026, 10, 1)
    await db.commit()

    # Same content again (as on every `docker compose up`): the review stays.
    await seed_knowledge(db, {"departments": [], "schemes": [_row(slug)]})
    assert await _status(db, slug) == ("verified", dt.date(2026, 10, 1))

    # The benefit changed in the file: someone has to check it again.
    await seed_knowledge(
        db, {"departments": [], "schemes": [_row(slug, benefits="Rs 200 per month.")]}
    )
    assert await _status(db, slug) == ("needs_review", dt.date(2026, 10, 1))

    # A changed condition counts too.
    await seed_knowledge(
        db,
        {"departments": [], "schemes": [_row(slug, benefits="Rs 200 per month.", conditions=[])]},
    )
    scheme = await db.scalar(select(Scheme).where(Scheme.slug == slug))
    assert scheme is not None
    await db.refresh(scheme, ["conditions"])
    assert scheme.conditions == []
