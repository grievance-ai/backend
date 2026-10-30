"""Human-readable account identifiers (separate from UUID primary keys).

Produces short, prefixed, collision-resistant IDs such as ``ID7QK2M9XT4A``,
used as the public ``uid`` on accounts.
"""

import secrets
import string

ALPHABET = string.ascii_uppercase + string.digits
DEFAULT_PREFIX = "ID"
DEFAULT_LENGTH = 10


def generate_uid(prefix: str = DEFAULT_PREFIX, length: int = DEFAULT_LENGTH) -> str:
    body = "".join(secrets.choice(ALPHABET) for _ in range(length))
    return f"{prefix}{body}"
