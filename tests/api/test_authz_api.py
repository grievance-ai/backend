"""Integration tests for authentication + RBAC on protected routes."""

import time
import uuid

from app.models.api_key import APIKey
from app.models.user import User
from app.services.api_key_verifier import expected_signature
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import LoginAs, MakeUser

RESOURCE = "/api/v2/xuanwu/resource"
ADMIN = "/api/v2/xuanwu/admin"


async def test_protected_route_requires_authentication(client: AsyncClient) -> None:
    resp = await client.get(f"{RESOURCE}/users/me")
    assert resp.status_code == 401
    assert "authz.unauthorized" in resp.json()["errors"]


async def test_member_can_access_own_resource(client: AsyncClient, login_as: LoginAs) -> None:
    await login_as(role="member")
    resp = await client.get(f"{RESOURCE}/users/me")
    assert resp.status_code == 200
    assert resp.json()["data"]["role"] == "member"


async def test_member_forbidden_on_admin(client: AsyncClient, login_as: LoginAs) -> None:
    await login_as(role="member")
    resp = await client.get(f"{ADMIN}/ping")
    assert resp.status_code == 403
    assert "authz.forbidden" in resp.json()["errors"]


async def test_admin_allowed_on_admin(client: AsyncClient, login_as: LoginAs) -> None:
    await login_as(role="admin")
    resp = await client.get(f"{ADMIN}/ping")
    assert resp.status_code == 200
    assert resp.json()["data"]["pong"] is True


async def test_csrf_required_on_state_changing_request(
    client: AsyncClient, login_as: LoginAs
) -> None:
    _, csrf = await login_as(role="admin")
    missing = await client.post(f"{ADMIN}/ping")
    assert missing.status_code == 403
    assert "identity.csrf.invalid" in missing.json()["errors"]

    present = await client.post(f"{ADMIN}/ping", headers={"X-CSRF-Token": csrf})
    assert present.status_code == 200


async def test_banned_user_is_rejected(
    client: AsyncClient, db: AsyncSession, login_as: LoginAs
) -> None:
    user, _ = await login_as(role="member")
    # ban the user; the existing access cookie must stop working
    user.state = "banned"
    await db.commit()
    resp = await client.get(f"{RESOURCE}/users/me")
    assert resp.status_code == 401


async def test_api_key_authorizes_via_hmac(
    client: AsyncClient, db: AsyncSession, make_user: MakeUser
) -> None:
    user: User = await make_user(role="member")
    kid, secret = "testkid" + uuid.uuid4().hex[:8], "super-secret-value-123"
    db.add(
        APIKey(
            kid=kid,
            secret=secret,
            key_holder_account_id=user.id,
            key_holder_account_type="User",
            state="active",
            scope=["read"],
        )
    )
    await db.commit()

    nonce = str(int(time.time() * 1000))
    signature = expected_signature(secret, nonce, kid)
    resp = await client.get(
        f"{RESOURCE}/users/me",
        headers={"X-Auth-Apikey": kid, "X-Auth-Nonce": nonce, "X-Auth-Signature": signature},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["email"] == user.email


async def test_api_key_bad_signature_rejected(
    client: AsyncClient, db: AsyncSession, make_user: MakeUser
) -> None:
    user: User = await make_user(role="member")
    kid = "testkid" + uuid.uuid4().hex[:8]
    db.add(
        APIKey(
            kid=kid,
            secret="the-real-secret",
            key_holder_account_id=user.id,
            key_holder_account_type="User",
            state="active",
        )
    )
    await db.commit()

    nonce = str(int(time.time() * 1000))
    resp = await client.get(
        f"{RESOURCE}/users/me",
        headers={"X-Auth-Apikey": kid, "X-Auth-Nonce": nonce, "X-Auth-Signature": "deadbeef"},
    )
    assert resp.status_code == 401
