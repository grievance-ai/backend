"""`security.write_keypair` — explicit RS256 keypair generation (console)."""

from pathlib import Path

import pytest
from app.core import security
from app.core.config import settings


@pytest.fixture
def key_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    private = tmp_path / "keys" / "jwt_private.pem"
    public = tmp_path / "keys" / "jwt_public.pem"
    monkeypatch.setattr(settings, "jwt_private_key_path", str(private))
    monkeypatch.setattr(settings, "jwt_public_key_path", str(public))
    security._keys.cache_clear()
    return private, public


def test_write_keypair_creates_usable_keys(key_paths: tuple[Path, Path]) -> None:
    private, public = key_paths
    written_private, written_public = security.write_keypair()

    assert written_private == private and written_public == public
    assert "PRIVATE KEY" in private.read_text()
    assert "PUBLIC KEY" in public.read_text()
    # The fresh keys actually sign and verify a token round-trip.
    token, _ = security.create_access_token("uid-1", "member")
    assert security.decode_token(token, expected_type=security.ACCESS_TYPE)["uid"] == "uid-1"


def test_write_keypair_refuses_overwrite_without_force(key_paths: tuple[Path, Path]) -> None:
    security.write_keypair()
    with pytest.raises(FileExistsError):
        security.write_keypair()


def test_write_keypair_force_overwrites(key_paths: tuple[Path, Path]) -> None:
    private, _ = key_paths
    security.write_keypair()
    first = private.read_text()
    security.write_keypair(force=True)
    assert private.read_text() != first
