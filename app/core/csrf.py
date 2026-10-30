"""Double-submit CSRF protection.

A random token is minted at login, stored in a readable (non-httpOnly) cookie,
and must be echoed in the ``X-CSRF-Token`` header on state-changing requests.
The cookie and header are compared in constant time.
"""

import hmac
import secrets

from fastapi import Request

from app.core.config import settings
from app.core.errors import APIError

CSRF_HEADER = "X-CSRF-Token"


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def tokens_match(cookie_value: str | None, header_value: str | None) -> bool:
    if not cookie_value or not header_value:
        return False
    return hmac.compare_digest(cookie_value, header_value)


async def csrf_protect(request: Request) -> None:
    """Dependency for state-changing routes; raises 403 on mismatch."""
    cookie_value = request.cookies.get(settings.csrf_cookie_name)
    header_value = request.headers.get(CSRF_HEADER)
    if not tokens_match(cookie_value, header_value):
        raise APIError(["identity.csrf.invalid"], 403)
