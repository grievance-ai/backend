"""Integration tests for the resource endpoints (the user's own account)."""

import uuid

import pyotp
from httpx import AsyncClient

IDENTITY = "/api/v2/xuanwu/identity"
RESOURCE = "/api/v2/xuanwu/resource"
PASSWORD = "Tr0ub4dour&3xtra"


def _email() -> str:
    return f"u{uuid.uuid4().hex[:12]}@example.com"


async def _register(client: AsyncClient) -> tuple[str, str]:
    """Register a user; returns (email, csrf_token). Cookies are stored on the client."""
    email = _email()
    resp = await client.post(f"{IDENTITY}/users", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 201, resp.text
    return email, resp.json()["data"]["csrf_token"]


def _csrf(token: str) -> dict[str, str]:
    return {"X-CSRF-Token": token}


async def test_get_me(client: AsyncClient) -> None:
    email, _ = await _register(client)
    resp = await client.get(f"{RESOURCE}/users/me")
    assert resp.status_code == 200
    assert resp.json()["data"]["email"] == email


async def test_update_me(client: AsyncClient) -> None:
    _, csrf = await _register(client)
    username = "user_" + uuid.uuid4().hex[:8]
    resp = await client.put(
        f"{RESOURCE}/users/me", json={"username": username}, headers=_csrf(csrf)
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["username"] == username


async def test_change_password_then_login(client: AsyncClient) -> None:
    email, csrf = await _register(client)
    new_password = "An0ther!Str0ng_Pass"
    resp = await client.put(
        f"{RESOURCE}/users/password",
        json={"old_password": PASSWORD, "new_password": new_password},
        headers=_csrf(csrf),
    )
    assert resp.status_code == 200
    login = await client.post(
        f"{IDENTITY}/sessions", json={"email": email, "password": new_password}
    )
    assert login.status_code == 200


async def test_profile_upsert_and_get(client: AsyncClient) -> None:
    _, csrf = await _register(client)
    assert (await client.get(f"{RESOURCE}/profiles/me")).status_code == 404
    created = await client.post(
        f"{RESOURCE}/profiles",
        json={"first_name": "Alice", "last_name": "Smith", "country": "AU"},
        headers=_csrf(csrf),
    )
    assert created.status_code == 201
    fetched = await client.get(f"{RESOURCE}/profiles/me")
    assert fetched.status_code == 200
    assert fetched.json()["data"]["first_name"] == "Alice"


async def test_phone_create_and_verify(client: AsyncClient) -> None:
    _, csrf = await _register(client)
    created = await client.post(
        f"{RESOURCE}/phones", json={"country": "AU", "number": "+61400000111"}, headers=_csrf(csrf)
    )
    assert created.status_code == 201
    body = created.json()["data"]
    phone_id, code = body["phone"]["id"], body["verification_code"]
    assert code
    verified = await client.post(
        f"{RESOURCE}/phones/verify", json={"phone_id": phone_id, "code": code}, headers=_csrf(csrf)
    )
    assert verified.status_code == 200
    assert verified.json()["data"]["validated_at"] is not None


async def test_labels_create_list_and_duplicate(client: AsyncClient) -> None:
    _, csrf = await _register(client)
    created = await client.post(
        f"{RESOURCE}/labels", json={"key": "newsletter", "value": "subscribed"}, headers=_csrf(csrf)
    )
    assert created.status_code == 201
    listed = await client.get(f"{RESOURCE}/labels")
    assert any(label["key"] == "newsletter" for label in listed.json()["data"])
    duplicate = await client.post(
        f"{RESOURCE}/labels", json={"key": "newsletter", "value": "subscribed"}, headers=_csrf(csrf)
    )
    assert duplicate.status_code == 409


async def test_data_storage_roundtrip(client: AsyncClient) -> None:
    _, csrf = await _register(client)
    created = await client.post(
        f"{RESOURCE}/data_storage",
        json={"title": "note", "data": "secret value"},
        headers=_csrf(csrf),
    )
    assert created.status_code == 201
    listed = await client.get(f"{RESOURCE}/data_storage")
    assert listed.json()["data"][0]["data"] == "secret value"


async def test_documents_hide_number(client: AsyncClient) -> None:
    _, csrf = await _register(client)
    created = await client.post(
        f"{RESOURCE}/documents",
        data={"doc_type": "passport", "doc_number": "X1234567"},
        files={"upload": ("passport.pdf", b"%PDF-1.4 bytes", "application/pdf")},
        headers=_csrf(csrf),
    )
    assert created.status_code == 201
    assert "doc_number" not in created.json()["data"]
    listed = await client.get(f"{RESOURCE}/documents/me")
    assert listed.json()["data"][0]["doc_type"] == "passport"


async def test_csrf_required_on_resource_write(client: AsyncClient) -> None:
    await _register(client)
    resp = await client.post(f"{RESOURCE}/labels", json={"key": "k", "value": "v"})
    assert resp.status_code == 403
    assert "identity.csrf.invalid" in resp.json()["errors"]


async def test_api_keys_require_2fa(client: AsyncClient) -> None:
    _, csrf = await _register(client)
    resp = await client.post(
        f"{RESOURCE}/api_keys", json={"otp_code": "000000"}, headers=_csrf(csrf)
    )
    assert resp.status_code == 403
    assert "resource.api_key.otp_required" in resp.json()["errors"]


async def _enable_2fa(client: AsyncClient, csrf: str) -> str:
    generated = await client.post(f"{RESOURCE}/otp/generate_qrcode", headers=_csrf(csrf))
    secret = generated.json()["data"]["secret"]
    code = pyotp.TOTP(secret).now()
    enabled = await client.post(f"{RESOURCE}/otp/enable", json={"code": code}, headers=_csrf(csrf))
    assert enabled.status_code == 200, enabled.text
    return str(secret)


async def test_otp_enable_and_api_key_lifecycle(client: AsyncClient) -> None:
    _, csrf = await _register(client)
    secret = await _enable_2fa(client, csrf)
    assert (await client.get(f"{RESOURCE}/users/me")).json()["data"]["otp"] is True

    code = pyotp.TOTP(secret).now()
    created = await client.post(
        f"{RESOURCE}/api_keys", json={"otp_code": code, "scope": ["read"]}, headers=_csrf(csrf)
    )
    assert created.status_code == 201
    data = created.json()["data"]
    assert data["secret"]  # returned once
    kid = data["kid"]

    listed = await client.get(f"{RESOURCE}/api_keys")
    assert listed.json()["data"][0]["kid"] == kid
    assert "secret" not in listed.json()["data"][0]

    deleted = await client.request(
        "DELETE",
        f"{RESOURCE}/api_keys/{kid}",
        json={"otp_code": pyotp.TOTP(secret).now()},
        headers=_csrf(csrf),
    )
    assert deleted.status_code == 200
