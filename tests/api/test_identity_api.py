"""Integration tests for the identity endpoints (requires database + Redis)."""

import uuid

from httpx import AsyncClient

IDENTITY = "/api/v2/xuanwu/identity"
PASSWORD = "Tr0ub4dour&3xtra"


def _email() -> str:
    return f"u{uuid.uuid4().hex[:12]}@example.com"


async def _register(client: AsyncClient, email: str, password: str = PASSWORD) -> None:
    resp = await client.post(f"{IDENTITY}/users", json={"email": email, "password": password})
    assert resp.status_code == 201, resp.text


async def test_register_login_logout_happy_path(client: AsyncClient) -> None:
    email = _email()
    resp = await client.post(f"{IDENTITY}/users", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 201
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["user"]["email"] == email
    assert body["data"]["csrf_token"]
    assert client.cookies.get("access_token")
    assert client.cookies.get("refresh_token")

    assert (await client.delete(f"{IDENTITY}/sessions")).status_code == 200

    login = await client.post(f"{IDENTITY}/sessions", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200
    assert login.json()["data"]["user"]["email"] == email


async def test_duplicate_email_rejected(client: AsyncClient) -> None:
    email = _email()
    await _register(client, email)
    resp = await client.post(f"{IDENTITY}/users", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 409
    assert resp.json()["success"] is False
    assert "identity.user.email_taken" in resp.json()["errors"]


async def test_weak_password_rejected(client: AsyncClient) -> None:
    resp = await client.post(f"{IDENTITY}/users", json={"email": _email(), "password": "weak"})
    assert resp.status_code == 422
    assert any(key.startswith("password.") for key in resp.json()["errors"])


async def test_wrong_password_rejected(client: AsyncClient) -> None:
    email = _email()
    await _register(client, email)
    await client.delete(f"{IDENTITY}/sessions")
    resp = await client.post(
        f"{IDENTITY}/sessions", json={"email": email, "password": "WrongPass1!"}
    )
    assert resp.status_code == 401
    assert "identity.session.invalid_credentials" in resp.json()["errors"]


async def test_email_confirmation_flow(client: AsyncClient) -> None:
    email = _email()
    await _register(client, email)
    generated = await client.post(f"{IDENTITY}/email/generate_code", json={"email": email})
    token = generated.json()["data"]["confirmation_token"]
    assert token
    confirmed = await client.post(f"{IDENTITY}/email/confirm_code", json={"token": token})
    assert confirmed.status_code == 200
    assert confirmed.json()["data"]["state"] == "active"


async def test_password_reset_flow(client: AsyncClient) -> None:
    email = _email()
    await _register(client, email)
    generated = await client.post(f"{IDENTITY}/password/generate_code", json={"email": email})
    token = generated.json()["data"]["reset_token"]
    assert token

    validated = await client.get(f"{IDENTITY}/password/validate", params={"token": token})
    assert validated.json()["data"]["valid"] is True

    new_password = "N3w!str0ng_Phrase"
    reset = await client.post(
        f"{IDENTITY}/password/confirm_code", json={"token": token, "password": new_password}
    )
    assert reset.status_code == 200

    login = await client.post(
        f"{IDENTITY}/sessions", json={"email": email, "password": new_password}
    )
    assert login.status_code == 200


async def test_login_lockout_after_repeated_failures(client: AsyncClient) -> None:
    email = _email()
    await _register(client, email)
    await client.delete(f"{IDENTITY}/sessions")
    for _ in range(5):
        failed = await client.post(
            f"{IDENTITY}/sessions", json={"email": email, "password": "WrongPass1!"}
        )
        assert failed.status_code == 401
    locked = await client.post(
        f"{IDENTITY}/sessions", json={"email": email, "password": "WrongPass1!"}
    )
    assert locked.status_code == 429
    assert "identity.session.locked" in locked.json()["errors"]


async def test_refresh_rotates_session(client: AsyncClient) -> None:
    await _register(client, _email())
    refreshed = await client.post(f"{IDENTITY}/sessions/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["data"]["csrf_token"]


async def test_meta_endpoints(client: AsyncClient) -> None:
    assert (await client.get(f"{IDENTITY}/ping")).json()["data"]["ping"] == "pong"
    assert "time" in (await client.get(f"{IDENTITY}/time")).json()["data"]
    configs = (await client.get(f"{IDENTITY}/configs")).json()["data"]
    assert configs["password"]["min_length"] == 8
    assert configs["captcha_provider"] == "none"
