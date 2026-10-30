"""Application-level field encryption with a weekly-rotating key.

Values are encrypted with Fernet using a key derived from the app secret and a
weekly salt; the salt is packed with the ciphertext so old values stay
decryptable after the key rotates. The ``blind_index`` (a deterministic keyed
hash) lets encrypted columns still be looked up by value.
"""

import base64
import datetime as dt
import hashlib

from cryptography.fernet import Fernet
from sqlalchemy import Text
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.types import TypeDecorator

from app.core.config import settings
from app.utils.blind_index import blind_index

__all__ = ["EncryptedString", "blind_index", "decrypt", "encrypt"]

_SEPARATOR = "."


def _current_salt() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y%W")  # year + ISO week number


def _derive_key(salt: str) -> bytes:
    digest = hashlib.sha256(f"{settings.secret_key}:{salt}".encode()).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt(value: str) -> str:
    salt = _current_salt()
    token = Fernet(_derive_key(salt)).encrypt(value.encode())
    return f"{salt}{_SEPARATOR}{token.decode()}"


def decrypt(packed: str) -> str:
    salt, token = packed.split(_SEPARATOR, 1)
    return Fernet(_derive_key(salt)).decrypt(token.encode()).decode()


class EncryptedString(TypeDecorator[str]):
    """Transparently encrypts on write and decrypts on read (stored as TEXT)."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return encrypt(value)

    def process_result_value(self, value: str | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return decrypt(value)
