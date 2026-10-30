"""Password hashing and RS256 JWT issuance/verification.

Tokens are signed with an RSA private key and verified with the matching public
key. In development the keypair is generated on first use; in production the
keys must be provided at the configured paths.
"""

import datetime as dt
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from passlib.context import CryptContext

from app.core.config import settings

ALGORITHM = "RS256"
ACCESS_TYPE = "session"
REFRESH_TYPE = "refresh"

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)


# --- passwords ---------------------------------------------------------------
def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, digest: str) -> bool:
    return _pwd_context.verify(password, digest)


# --- RSA keys ----------------------------------------------------------------
def _generate_keypair() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


def write_keypair(*, force: bool = False) -> tuple[Path, Path]:
    """Generate and persist an RS256 keypair at the configured paths.

    Returns the ``(private, public)`` paths. Refuses to overwrite existing keys
    unless ``force`` is set — rotating keys invalidates every issued token.
    """
    private_path = Path(settings.jwt_private_key_path)
    public_path = Path(settings.jwt_public_key_path)
    if not force and (private_path.exists() or public_path.exists()):
        raise FileExistsError("JWT keys already exist; pass force=True to overwrite.")
    private_pem, public_pem = _generate_keypair()
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_text(private_pem)
    public_path.write_text(public_pem)
    private_path.chmod(0o600)
    _keys.cache_clear()
    return private_path, public_path


@lru_cache
def _keys() -> tuple[str, str]:
    private_path = Path(settings.jwt_private_key_path)
    public_path = Path(settings.jwt_public_key_path)
    if private_path.exists() and public_path.exists():
        return private_path.read_text(), public_path.read_text()
    if settings.is_production:
        raise RuntimeError("JWT keys are missing; provide them in production.")
    private_pem, public_pem = _generate_keypair()
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_text(private_pem)
    public_path.write_text(public_pem)
    return private_pem, public_pem


# --- JWT ---------------------------------------------------------------------
def _encode(payload: dict[str, Any]) -> str:
    return jwt.encode(payload, _keys()[0], algorithm=ALGORITHM)


def create_token(
    *, user_id: str, token_type: str, ttl: int, extra: dict[str, Any] | None = None
) -> tuple[str, str]:
    """Return ``(token, jti)`` for a token of the given type."""
    jti = uuid.uuid4().hex
    now = dt.datetime.now(dt.UTC)
    payload: dict[str, Any] = {
        "sub": token_type,
        "uid": user_id,
        "jti": jti,
        "iat": now,
        "exp": now + dt.timedelta(seconds=ttl),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    if extra:
        payload.update(extra)
    return _encode(payload), jti


def create_access_token(user_id: str, role: str) -> tuple[str, str]:
    return create_token(
        user_id=user_id,
        token_type=ACCESS_TYPE,
        ttl=settings.access_token_ttl,
        extra={"role": role},
    )


def create_refresh_token(user_id: str, role: str) -> tuple[str, str]:
    return create_token(
        user_id=user_id,
        token_type=REFRESH_TYPE,
        ttl=settings.refresh_token_ttl,
        extra={"role": role},
    )


def decode_token(token: str, expected_type: str | None = None) -> dict[str, Any]:
    """Verify and decode a token; raises ``jwt.InvalidTokenError`` on any problem."""
    payload: dict[str, Any] = jwt.decode(
        token,
        _keys()[1],
        algorithms=[ALGORITHM],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
    )
    if expected_type is not None and payload.get("sub") != expected_type:
        raise jwt.InvalidTokenError("unexpected token type")
    return payload
