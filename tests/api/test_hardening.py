"""Perimeter hardening: captcha gating, secure headers, rate limiting."""

import uuid

from app.core.config import settings
from app.core.ratelimit import rate_limit_handler
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

IDENTITY = "/api/v2/xuanwu/identity"
PASSWORD = "Tr0ub4dour&3xtra"


def _email() -> str:
    return f"u{uuid.uuid4().hex[:12]}@example.com"


# --- captcha -----------------------------------------------------------------
async def test_register_requires_captcha_when_enabled(client: AsyncClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(settings, "captcha_provider", "recaptcha")
    resp = await client.post(f"{IDENTITY}/users", json={"email": _email(), "password": PASSWORD})
    assert resp.status_code == 422
    assert "identity.captcha.invalid" in resp.json()["errors"]


async def test_register_works_when_captcha_disabled(client: AsyncClient) -> None:
    # Default provider is "none" → captcha is a no-op.
    resp = await client.post(f"{IDENTITY}/users", json={"email": _email(), "password": PASSWORD})
    assert resp.status_code == 201


# --- secure headers ----------------------------------------------------------
async def test_security_headers_present(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"


# --- rate limiting -----------------------------------------------------------
async def test_rate_limit_returns_429_envelope() -> None:
    """A fresh app + in-memory limiter proves the limiter + our 429 envelope."""
    app = FastAPI()
    app.state.limiter = Limiter(
        key_func=get_remote_address, default_limits=["1/minute"], storage_uri="memory://"
    )
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
    app.add_middleware(SlowAPIMiddleware)

    @app.get("/ping")
    async def ping(request: Request) -> dict[str, bool]:
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        assert (await http.get("/ping")).status_code == 200
        limited = await http.get("/ping")
        assert limited.status_code == 429
        assert limited.json()["errors"] == ["authz.rate_limited"]
