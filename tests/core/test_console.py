"""Operator console (`app.console`) — command wiring and the no-DB commands."""

import getpass
from pathlib import Path

import pytest
from app import console
from app.core import security
from app.core.config import settings


@pytest.fixture
def key_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    private = tmp_path / "keys" / "jwt_private.pem"
    monkeypatch.setattr(settings, "jwt_private_key_path", str(private))
    monkeypatch.setattr(settings, "jwt_public_key_path", str(tmp_path / "keys" / "jwt_public.pem"))
    security._keys.cache_clear()
    return private


def test_generate_keys_command(key_paths: Path) -> None:
    assert console.main(["generate-keys"]) == 0
    assert key_paths.exists()
    # A second call without --force fails rather than clobbering the keys.
    assert console.main(["generate-keys"]) == 1
    assert console.main(["generate-keys", "--force"]) == 0


def test_parser_requires_a_subcommand() -> None:
    with pytest.raises(SystemExit):
        console.main([])


def test_create_superadmin_requires_a_password(monkeypatch: pytest.MonkeyPatch) -> None:
    # No --password and an empty interactive prompt → refuse, never touch the DB.
    monkeypatch.setattr(getpass, "getpass", lambda *_: "")
    assert console.main(["create-superadmin", "--email", "a@example.com"]) == 1


def test_create_superadmin_reports_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_create(email: str, username: str | None, password: str) -> str:
        assert (email, password) == ("a@example.com", "secret")
        return "IDFAKEUID"

    monkeypatch.setattr(console, "_create_superadmin", fake_create)
    argv = ["create-superadmin", "--email", "a@example.com", "--password", "secret"]
    assert console.main(argv) == 0
