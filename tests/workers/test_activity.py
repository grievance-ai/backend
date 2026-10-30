"""Audit trail: security-relevant actions land in the immutable activities log."""

import uuid

import pytest
from app.db.sync_session import SyncSessionLocal
from app.integrations import geoip
from app.models.activity import Activity, ActivityImmutableError
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

IDENTITY = "/api/v2/xuanwu/identity"
PASSWORD = "Tr0ub4dour&3xtra"


def _email() -> str:
    return f"u{uuid.uuid4().hex[:12]}@example.com"


async def _activities(db: AsyncSession, user_id: uuid.UUID) -> list[Activity]:
    rows = await db.scalars(select(Activity).where(Activity.user_id == user_id))
    return list(rows.all())


# --- GeoIP (no database) -----------------------------------------------------
def test_geoip_returns_none_for_private_and_default_provider() -> None:
    assert geoip.resolve_country(None) is None
    assert geoip.resolve_country("127.0.0.1") is None
    assert geoip.resolve_country("10.0.0.5") is None
    # Public IP, but the default `none` provider does not resolve.
    assert geoip.resolve_country("8.8.8.8") is None


# --- request flows write activities ------------------------------------------
async def test_register_is_audited(client: AsyncClient, db: AsyncSession) -> None:
    resp = await client.post(f"{IDENTITY}/users", json={"email": _email(), "password": PASSWORD})
    user_id = uuid.UUID(resp.json()["data"]["user"]["id"])

    acts = await _activities(db, user_id)
    assert [(a.topic, a.action, a.result) for a in acts] == [("user", "register", "succeed")]
    assert acts[0].category == "identity"


async def test_login_success_and_failure_are_audited(client: AsyncClient, db: AsyncSession) -> None:
    email = _email()
    resp = await client.post(f"{IDENTITY}/users", json={"email": email, "password": PASSWORD})
    user_id = uuid.UUID(resp.json()["data"]["user"]["id"])

    await client.post(f"{IDENTITY}/sessions", json={"email": email, "password": "wrong-pass-123"})
    await client.post(f"{IDENTITY}/sessions", json={"email": email, "password": PASSWORD})

    results = {(a.action, a.result) for a in await _activities(db, user_id)}
    assert ("login", "failed") in results
    assert ("login", "succeed") in results


async def test_logout_is_audited(client: AsyncClient, db: AsyncSession) -> None:
    email = _email()
    resp = await client.post(f"{IDENTITY}/users", json={"email": email, "password": PASSWORD})
    user_id = uuid.UUID(resp.json()["data"]["user"]["id"])
    # Registration already set auth cookies on the client.
    await client.delete(f"{IDENTITY}/sessions")

    actions = {a.action for a in await _activities(db, user_id)}
    assert "logout" in actions


# --- immutability ------------------------------------------------------------
# Exercised through a synchronous session — the same path the Celery worker uses
# to write activities. The `db` fixture is present only to skip when no DB.
async def test_activity_cannot_be_updated_or_deleted(db: AsyncSession) -> None:
    with SyncSessionLocal() as setup:
        activity = Activity(category="identity", topic="session", action="login", result="succeed")
        setup.add(activity)
        setup.commit()
        activity_id = activity.id

    with SyncSessionLocal() as session:
        loaded = session.get(Activity, activity_id)
        assert loaded is not None
        loaded.result = "failed"
        with pytest.raises(ActivityImmutableError):
            session.commit()

    with SyncSessionLocal() as session:
        loaded = session.get(Activity, activity_id)
        assert loaded is not None
        session.delete(loaded)
        with pytest.raises(ActivityImmutableError):
            session.commit()

    # The record survived both attempts unchanged.
    with SyncSessionLocal() as session:
        survivor = session.get(Activity, activity_id)
        assert survivor is not None
        assert survivor.result == "succeed"
