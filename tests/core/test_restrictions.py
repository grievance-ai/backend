"""IP/geo restriction engine + admin restriction CRUD."""

import json
import uuid
from typing import Any

import pytest
import redis.asyncio as redis
from app.core import restrictions
from app.core.errors import APIError
from app.core.security import hash_password
from app.models.user import User
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

IDENTITY = "/api/v2/xuanwu/identity"
ADMIN = "/api/v2/xuanwu/admin"
PASSWORD = "Tr0ub4dour&3xtra"
IP = "203.0.113.7"


def _request(method: str, path: str, ip: str = IP) -> Request:
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [],
        "query_string": b"",
        "client": (ip, 0),
    }
    return Request(scope)


def _table(category: str, scope: str, value: str, code: int) -> dict[str, Any]:
    base: dict[str, Any] = {
        c: {s: [] for s in restrictions.SCOPES} for c in restrictions.CATEGORIES
    }
    base[category][scope].append([value, code])
    return base


async def _seed(fake_redis: redis.Redis, table: dict[str, Any]) -> None:
    await fake_redis.setex(restrictions._CACHE_KEY, 300, json.dumps(table))


# --- pure logic --------------------------------------------------------------
def test_assign_code() -> None:
    assert restrictions.assign_code("maintenance", "all", None) == 471
    assert restrictions.assign_code("blacklist", "ip", None) == 401
    assert restrictions.assign_code("blacklist", "country", None) == 423
    assert restrictions.assign_code("whitelist", "ip", None) is None
    assert restrictions.assign_code("blacklist", "ip", 418) == 418  # explicit code kept


# --- evaluate (seeded cache, no DB) ------------------------------------------
async def test_blacklisted_ip_is_denied(fake_redis: redis.Redis) -> None:
    await _seed(fake_redis, _table("blacklist", "ip", IP, 401))
    with pytest.raises(APIError) as exc:
        await restrictions.evaluate(_request("GET", "/x"), fake_redis)
    assert exc.value.status_code == 401
    assert exc.value.keys == ["authz.restrict.blacklist"]


async def test_maintenance_returns_471(fake_redis: redis.Redis) -> None:
    await _seed(fake_redis, _table("maintenance", "all", "all", 471))
    with pytest.raises(APIError) as exc:
        await restrictions.evaluate(_request("GET", "/x"), fake_redis)
    assert exc.value.status_code == 471


async def test_subnet_match_is_denied(fake_redis: redis.Redis) -> None:
    await _seed(fake_redis, _table("blacklist", "ip_subnet", "203.0.113.0/24", 403))
    with pytest.raises(APIError):
        await restrictions.evaluate(_request("GET", "/x"), fake_redis)


async def test_whitelist_bypasses_blacklist(fake_redis: redis.Redis) -> None:
    table = _table("blacklist", "ip", IP, 401)
    table["whitelist"]["ip"].append([IP, None])
    await _seed(fake_redis, table)
    await restrictions.evaluate(_request("GET", "/x"), fake_redis)  # no raise


async def test_blocklogin_only_blocks_the_login_path(fake_redis: redis.Redis) -> None:
    await _seed(fake_redis, _table("blocklogin", "ip", IP, 401))
    await restrictions.evaluate(_request("GET", "/x"), fake_redis)  # other paths fine
    with pytest.raises(APIError) as exc:
        await restrictions.evaluate(_request("POST", f"{IDENTITY}/sessions"), fake_redis)
    assert exc.value.keys == ["authz.restrict.blocklogin"]


async def test_non_matching_ip_is_allowed(fake_redis: redis.Redis) -> None:
    await _seed(fake_redis, _table("blacklist", "ip", "198.51.100.1", 401))
    await restrictions.evaluate(_request("GET", "/x"), fake_redis)  # different IP → allowed


# --- admin CRUD (uses a non-matching IP so it never blocks the suite) --------
async def _login_superadmin(client: AsyncClient, db: AsyncSession) -> str:
    email = f"u{uuid.uuid4().hex[:12]}@example.com"
    db.add(User(email=email, password_digest=hash_password(PASSWORD), role="superadmin"))
    await db.commit()
    resp = await client.post(f"{IDENTITY}/sessions", json={"email": email, "password": PASSWORD})
    return str(resp.json()["data"]["csrf_token"])


async def test_admin_restriction_crud(client: AsyncClient, db: AsyncSession) -> None:
    csrf = await _login_superadmin(client, db)
    headers = {"X-CSRF-Token": csrf}

    created = await client.post(
        f"{ADMIN}/restrictions",
        json={"category": "blacklist", "scope": "ip", "value": "198.51.100.42"},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    body = created.json()["data"]
    assert body["code"] == 401  # default code for ip scope

    rid = body["id"]
    listed = await client.get(f"{ADMIN}/restrictions")
    assert any(r["id"] == rid for r in listed.json()["data"]["items"])

    disabled = await client.put(
        f"{ADMIN}/restrictions/{rid}", json={"state": "disabled"}, headers=headers
    )
    assert disabled.json()["data"]["state"] == "disabled"

    deleted = await client.request("DELETE", f"{ADMIN}/restrictions/{rid}", headers=headers)
    assert deleted.status_code == 200


async def test_invalid_restriction_value_rejected(client: AsyncClient, db: AsyncSession) -> None:
    csrf = await _login_superadmin(client, db)
    resp = await client.post(
        f"{ADMIN}/restrictions",
        json={"category": "blacklist", "scope": "ip", "value": "not-an-ip"},
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 422
    assert "admin.restriction.invalid_value" in resp.json()["errors"]
