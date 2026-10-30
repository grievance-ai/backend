"""Global request rate limiting (slowapi, Redis-backed).

A per-IP ceiling complements the Redis login-lockout from the auth service. The
limiter is keyed by client IP and shares state across workers via Redis. Limits
are disabled in tests so the suite isn't throttled.
"""

from typing import Any

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[settings.rate_limit_default],
    storage_uri=settings.redis_url,
    enabled=settings.rate_limit_enabled,
)


def rate_limit_handler(request: Request, exc: Any) -> JSONResponse:
    """Render a 429 in the uniform ``{success, errors}`` envelope."""
    return JSONResponse(
        status_code=429, content={"success": False, "errors": ["authz.rate_limited"]}
    )
