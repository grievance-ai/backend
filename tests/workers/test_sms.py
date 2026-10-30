"""Phone verification: SMS delivery and the level it unlocks."""

import uuid

from app.core.config import settings
from app.integrations.sms import get_provider, mock
from app.integrations.sms.aws_sns import AWSSNSProvider
from app.integrations.sms.twilio_sms import TwilioSMSProvider
from app.integrations.sms.twilio_verify import TwilioVerifyProvider
from httpx import AsyncClient

IDENTITY = "/api/v2/xuanwu/identity"
RESOURCE = "/api/v2/xuanwu/resource"
PASSWORD = "Tr0ub4dour&3xtra"
NUMBER = "+61400000000"


def _email() -> str:
    return f"u{uuid.uuid4().hex[:12]}@example.com"


def _csrf(token: str) -> dict[str, str]:
    return {"X-CSRF-Token": token}


# --- provider selection ------------------------------------------------------
def test_get_provider_honours_config(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(settings, "sms_provider", "twilio_sms")
    assert isinstance(get_provider(), TwilioSMSProvider)
    monkeypatch.setattr(settings, "sms_provider", "aws_sns")
    assert isinstance(get_provider(), AWSSNSProvider)
    monkeypatch.setattr(settings, "sms_provider", "twilio_verify")
    assert isinstance(get_provider(), TwilioVerifyProvider)


def test_self_managed_providers_compare_stored_code() -> None:
    """mock/twilio_sms/aws_sns verify by comparing the code we stored; Twilio
    Verify defers to its own remote check (manages_codes)."""
    assert get_provider().manages_codes is False  # mock, the default
    assert get_provider().check_code(number="x", code="123456", expected="123456") is True
    assert get_provider().check_code(number="x", code="000000", expected="123456") is False
    assert get_provider().check_code(number="x", code="123456", expected=None) is False
    assert TwilioVerifyProvider.manages_codes is True


# --- delivery + verification (database-backed) -------------------------------
async def _register(client: AsyncClient) -> str:
    resp = await client.post(f"{IDENTITY}/users", json={"email": _email(), "password": PASSWORD})
    assert resp.status_code == 201, resp.text
    return str(resp.json()["data"]["csrf_token"])


async def test_adding_a_phone_sends_the_code_by_sms(client: AsyncClient) -> None:
    csrf = await _register(client)
    resp = await client.post(f"{RESOURCE}/phones", json={"number": NUMBER}, headers=_csrf(csrf))
    assert resp.status_code == 201, resp.text

    code = resp.json()["data"]["verification_code"]
    assert [(m.to, m.body) for m in mock.outbox] == [
        (NUMBER, f"Your Rare Vintage verification code is {code}.")
    ]


async def test_verifying_phone_adds_label_and_bumps_level(client: AsyncClient) -> None:
    email_resp = await client.post(
        f"{IDENTITY}/users", json={"email": _email(), "password": PASSWORD}
    )
    csrf = email_resp.json()["data"]["csrf_token"]
    email = email_resp.json()["data"]["user"]["email"]

    # Verify email first so the phone (level 2) is contiguous with email (level 1).
    token = (await client.post(f"{IDENTITY}/email/generate_code", json={"email": email})).json()[
        "data"
    ]["confirmation_token"]
    await client.post(f"{IDENTITY}/email/confirm_code", json={"token": token})

    created = await client.post(f"{RESOURCE}/phones", json={"number": NUMBER}, headers=_csrf(csrf))
    phone_id = created.json()["data"]["phone"]["id"]
    code = created.json()["data"]["verification_code"]

    verified = await client.post(
        f"{RESOURCE}/phones/verify",
        json={"phone_id": phone_id, "code": code},
        headers=_csrf(csrf),
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["data"]["validated_at"] is not None

    me = await client.get(f"{RESOURCE}/users/me")
    assert me.json()["data"]["level"] == 2


async def test_wrong_code_is_rejected(client: AsyncClient) -> None:
    csrf = await _register(client)
    created = await client.post(f"{RESOURCE}/phones", json={"number": NUMBER}, headers=_csrf(csrf))
    phone_id = created.json()["data"]["phone"]["id"]
    code = created.json()["data"]["verification_code"]
    wrong = "111111" if code != "111111" else "222222"

    resp = await client.post(
        f"{RESOURCE}/phones/verify",
        json={"phone_id": phone_id, "code": wrong},
        headers=_csrf(csrf),
    )
    assert resp.status_code == 422
    assert "resource.phone.invalid_code" in resp.json()["errors"]
