"""Document storage: provider behaviour and the upload/list/delete API."""

import uuid

from app.core.config import settings
from app.integrations.storage import get_provider
from app.integrations.storage.local import LocalStorageProvider
from app.integrations.storage.s3 import S3StorageProvider
from httpx import AsyncClient

RESOURCE = "/api/v2/xuanwu/resource"
IDENTITY = "/api/v2/xuanwu/identity"
PASSWORD = "Tr0ub4dour&3xtra"
PDF = b"%PDF-1.4 fake document bytes"


def _email() -> str:
    return f"u{uuid.uuid4().hex[:12]}@example.com"


def _csrf(token: str) -> dict[str, str]:
    return {"X-CSRF-Token": token}


async def _register(client: AsyncClient) -> str:
    resp = await client.post(f"{IDENTITY}/users", json={"email": _email(), "password": PASSWORD})
    assert resp.status_code == 201, resp.text
    return str(resp.json()["data"]["csrf_token"])


# --- provider selection + local round trip (no database) ---------------------
def test_get_provider_honours_config(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(settings, "storage_provider", "s3")
    assert isinstance(get_provider(), S3StorageProvider)
    monkeypatch.setattr(settings, "storage_provider", "local")
    assert isinstance(get_provider(), LocalStorageProvider)


def test_local_provider_round_trip() -> None:
    provider = get_provider()
    result = provider.upload(
        PDF, filename="passport.pdf", content_type="application/pdf", user_id="u1", document_id="d1"
    )
    assert result.path.startswith("uploads/user_u1/document_d1/")
    assert result.path.endswith(".pdf")
    assert provider.exists(result.path)
    assert provider.get_url(result.path) == f"/{result.path}"

    assert provider.delete(result.path) is True
    assert provider.exists(result.path) is False
    assert provider.get_url(result.path) is None


# --- upload / list / delete API (database-backed) ----------------------------
async def test_upload_then_list_then_delete(client: AsyncClient) -> None:
    csrf = await _register(client)
    created = await client.post(
        f"{RESOURCE}/documents",
        data={"doc_type": "passport", "doc_number": "X1234567"},
        files={"upload": ("passport.pdf", PDF, "application/pdf")},
        headers=_csrf(csrf),
    )
    assert created.status_code == 201, created.text
    body = created.json()["data"]
    document_id = body["id"]
    assert body["doc_type"] == "passport"
    assert body["upload"].startswith("/uploads/user_")  # local URL to the stored file

    listed = await client.get(f"{RESOURCE}/documents/me")
    assert [d["id"] for d in listed.json()["data"]] == [document_id]

    deleted = await client.request(
        "DELETE", f"{RESOURCE}/documents/{document_id}", headers=_csrf(csrf)
    )
    assert deleted.status_code == 200
    after = await client.get(f"{RESOURCE}/documents/me")
    assert after.json()["data"] == []


async def test_disallowed_extension_is_rejected(client: AsyncClient) -> None:
    csrf = await _register(client)
    resp = await client.post(
        f"{RESOURCE}/documents",
        data={"doc_type": "passport", "doc_number": "X1234567"},
        files={"upload": ("malware.exe", b"MZ...", "application/octet-stream")},
        headers=_csrf(csrf),
    )
    assert resp.status_code == 422
    assert "resource.document.invalid_extension" in resp.json()["errors"]


async def test_oversize_upload_is_rejected(client: AsyncClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(settings, "upload_max_size", 8)
    csrf = await _register(client)
    resp = await client.post(
        f"{RESOURCE}/documents",
        data={"doc_type": "passport", "doc_number": "X1234567"},
        files={"upload": ("passport.pdf", PDF, "application/pdf")},
        headers=_csrf(csrf),
    )
    assert resp.status_code == 422
    assert "resource.document.too_large" in resp.json()["errors"]
