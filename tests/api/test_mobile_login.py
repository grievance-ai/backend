"""Prototype citizen login: mobile number + fixed OTP."""

import secrets

import pytest
from app.core.config import settings
from app.models.user import User
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

MOBILE_LOGIN = "/api/v2/xuanwu/identity/sessions/mobile"


def _mobile() -> str:
    # Random so re-runs against the persistent test database never collide.
    return "9" + "".join(secrets.choice("0123456789") for _ in range(9))


async def test_first_login_creates_citizen_with_profile(
    client: AsyncClient, db: AsyncSession
) -> None:
    mobile = _mobile()
    resp = await client.post(MOBILE_LOGIN, json={"mobile": mobile, "otp": "1111", "language": "pa"})

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["user"]["mobile"] == f"+91{mobile}"
    assert data["user"]["role"] == "citizen"
    assert data["user"]["preferred_language"] == "pa"
    assert data["user"]["email"] is None
    assert data["csrf_token"]
    assert settings.access_cookie_name in resp.cookies

    user = await db.scalar(
        select(User)
        .where(User.mobile == f"+91{mobile}")
        .options(selectinload(User.citizen_profile))
    )
    assert user is not None and user.citizen_profile is not None


async def test_second_login_reuses_the_account(client: AsyncClient) -> None:
    mobile = _mobile()
    first = await client.post(MOBILE_LOGIN, json={"mobile": mobile, "otp": "1111"})
    second = await client.post(MOBILE_LOGIN, json={"mobile": mobile, "otp": "1111"})
    assert first.json()["data"]["user"]["id"] == second.json()["data"]["user"]["id"]


async def test_wrong_otp_is_rejected(client: AsyncClient) -> None:
    resp = await client.post(MOBILE_LOGIN, json={"mobile": _mobile(), "otp": "1234"})
    assert resp.status_code == 401
    assert resp.json()["errors"] == ["identity.session.invalid_otp"]


@pytest.mark.parametrize("mobile", ["12345", "5876543210", "98765432100", "98765abcde"])
async def test_invalid_mobile_is_rejected(client: AsyncClient, mobile: str) -> None:
    resp = await client.post(MOBILE_LOGIN, json={"mobile": mobile, "otp": "1111"})
    assert resp.status_code == 422


async def test_disabled_in_production(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "app_env", "production")
    resp = await client.post(MOBILE_LOGIN, json={"mobile": _mobile(), "otp": "1111"})
    assert resp.status_code == 403
