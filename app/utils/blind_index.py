"""Deterministic blind index for encrypted, searchable columns.

A keyed HMAC of a normalized value. Storing it alongside an encrypted column
lets us look rows up by value (``WHERE phone_index = blind_index(input)``)
without decrypting the table.
"""

import hashlib
import hmac

from app.core.config import settings


def blind_index(value: str) -> str:
    normalized = value.strip().lower().encode("utf-8")
    return hmac.new(
        settings.blind_index_key.encode("utf-8"), normalized, hashlib.sha256
    ).hexdigest()
