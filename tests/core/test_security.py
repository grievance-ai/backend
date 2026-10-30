import jwt
import pytest
from app.core import security


def test_password_hash_and_verify() -> None:
    digest = security.hash_password("S3cure!passphrase")
    assert digest != "S3cure!passphrase"
    assert security.verify_password("S3cure!passphrase", digest)
    assert not security.verify_password("wrong", digest)


def test_access_token_roundtrip() -> None:
    token, jti = security.create_access_token("user-1", "member")
    payload = security.decode_token(token, expected_type=security.ACCESS_TYPE)
    assert payload["uid"] == "user-1"
    assert payload["role"] == "member"
    assert payload["jti"] == jti
    assert payload["sub"] == security.ACCESS_TYPE


def test_refresh_token_type_is_enforced() -> None:
    token, _ = security.create_refresh_token("user-1", "member")
    with pytest.raises(jwt.InvalidTokenError):
        security.decode_token(token, expected_type=security.ACCESS_TYPE)
    payload = security.decode_token(token, expected_type=security.REFRESH_TYPE)
    assert payload["sub"] == security.REFRESH_TYPE


def test_tampered_token_is_rejected() -> None:
    token, _ = security.create_access_token("user-1", "member")
    header, payload, signature = token.split(".")
    flipped = "B" if payload[0] != "B" else "C"
    tampered = f"{header}.{flipped}{payload[1:]}.{signature}"
    with pytest.raises(jwt.InvalidTokenError):
        security.decode_token(tampered)
