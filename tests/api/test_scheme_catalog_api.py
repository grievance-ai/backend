"""Citizens browse the scheme catalogue: active central and Punjab schemes only."""

import secrets
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest_asyncio
from app.db.knowledge import seed_knowledge
from app.models.scheme import Scheme
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

NS = "/api/v2/xuanwu"
SCHEMES = f"{NS}/resource/schemes"
PREFIX = "test-catalog-"


@pytest_asyncio.fixture(autouse=True)
async def _cleanup(db: AsyncSession) -> AsyncIterator[None]:
    yield
    await db.execute(delete(Scheme).where(Scheme.slug.like(f"{PREFIX}%")))
    await db.commit()


async def _login(client: AsyncClient) -> None:
    mobile = "9" + "".join(secrets.choice("0123456789") for _ in range(9))
    resp = await client.post(
        f"{NS}/identity/sessions/mobile", json={"mobile": mobile, "otp": "1111"}
    )
    assert resp.status_code == 200, resp.text


def _row(**overrides: Any) -> dict[str, Any]:
    return {
        "slug": f"{PREFIX}{uuid.uuid4().hex[:8]}",
        "name": "Test Catalogue Scheme",
        "level": "state",
        "state_code": "PB",
        "description": "Help for testing.",
        "benefits": "Rs 100.",
        "category_tags": ["pension"],
        "source_url": "https://example.gov.in/x",
        "conditions": [
            {"field": "age", "operator": "gte", "value": 60, "description": "You are 60+."},
            {"field": "a", "operator": "eq", "value": True, "description": "A.", "group": "g"},
            {"field": "b", "operator": "eq", "value": True, "description": "B.", "group": "g"},
        ],
        **overrides,
    }


async def test_login_required(client: AsyncClient) -> None:
    assert (await client.get(SCHEMES)).status_code == 401


async def test_citizens_see_active_punjab_and_central_schemes(
    db: AsyncSession, client: AsyncClient
) -> None:
    shown, inactive, haryana = _row(), _row(is_active=False), _row(state_code="HR")
    await seed_knowledge(db, {"departments": [], "schemes": [shown, inactive, haryana]})
    await _login(client)

    slugs = {s["slug"] for s in (await client.get(SCHEMES)).json()["data"]}
    assert shown["slug"] in slugs
    assert inactive["slug"] not in slugs and haryana["slug"] not in slugs

    detail = (await client.get(f"{SCHEMES}/{shown['slug']}")).json()["data"]
    assert detail["conditions"] == ["You are 60+."]
    assert detail["any_of_conditions"] == [["A.", "B."]]
    assert detail["source_url"] == "https://example.gov.in/x"
    assert detail["checked_on"] is None  # not checked by a person yet
    assert (await client.get(f"{SCHEMES}/{inactive['slug']}")).status_code == 404
