"""Branded email pipeline: rendering, provider selection, and enqueue wiring."""

import uuid

from app.core.config import settings
from app.emails import render_event
from app.integrations.email import get_provider, mock
from app.integrations.email.sendgrid_provider import SendGridEmailProvider
from app.integrations.email.smtp import SMTPEmailProvider
from httpx import AsyncClient

IDENTITY = "/api/v2/xuanwu/identity"
PASSWORD = "Tr0ub4dour&3xtra"


def _email() -> str:
    return f"u{uuid.uuid4().hex[:12]}@example.com"


# --- rendering (no database) -------------------------------------------------
def test_confirmation_email_is_branded() -> None:
    url = "https://app.example.com/confirm-email?token=abc"
    rendered = render_event("email_confirmation", "en", {"confirmation_url": url})
    assert rendered.subject == "Confirm your Rare Vintage email"
    assert "#b8923e" in rendered.html  # gold accent (EML-09)
    assert url in rendered.html
    # The plain-text alternative is stripped of markup but keeps the link.
    assert "<" not in rendered.text
    assert url in rendered.text


def test_unknown_language_falls_back_to_english() -> None:
    rendered = render_event("password_reset", "fr", {"reset_url": "https://x/y"})
    assert rendered.subject == "Reset your Rare Vintage password"
    assert "https://x/y" in rendered.html


# --- provider selection ------------------------------------------------------
def test_get_provider_honours_config(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(settings, "email_provider", "smtp")
    assert isinstance(get_provider(), SMTPEmailProvider)
    monkeypatch.setattr(settings, "email_provider", "sendgrid")
    assert isinstance(get_provider(), SendGridEmailProvider)


# --- enqueue wiring (database-backed) ----------------------------------------
async def test_register_sends_confirmation(client: AsyncClient) -> None:
    email = _email()
    await client.post(f"{IDENTITY}/users", json={"email": email, "password": PASSWORD})

    sent = [m for m in mock.outbox if m.to == email]
    assert len(sent) == 1
    assert sent[0].subject == "Confirm your Rare Vintage email"
    assert sent[0].from_email == settings.email_from


async def test_password_reset_request_sends_email(client: AsyncClient) -> None:
    email = _email()
    await client.post(f"{IDENTITY}/users", json={"email": email, "password": PASSWORD})
    mock.clear()

    await client.post(f"{IDENTITY}/password/generate_code", json={"email": email})

    sent = [m for m in mock.outbox if m.to == email]
    assert [m.subject for m in sent] == ["Reset your Rare Vintage password"]


async def test_password_reset_unknown_email_sends_nothing(client: AsyncClient) -> None:
    await client.post(f"{IDENTITY}/password/generate_code", json={"email": _email()})
    assert mock.outbox == []


async def test_login_sends_session_notice(client: AsyncClient) -> None:
    email = _email()
    await client.post(f"{IDENTITY}/users", json={"email": email, "password": PASSWORD})
    mock.clear()

    await client.post(f"{IDENTITY}/sessions", json={"email": email, "password": PASSWORD})

    subjects = [m.subject for m in mock.outbox if m.to == email]
    assert "New sign-in to your Rare Vintage account" in subjects
