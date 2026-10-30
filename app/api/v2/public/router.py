"""Public router: unauthenticated health/version/config endpoints.

Deliberately mounted *without* the restriction guard (see ``app.main``) so it
stays reachable for health checks during maintenance mode.
"""

from fastapi import APIRouter

from app.api.v2.public import general

public_router = APIRouter(prefix="/api/v2/xuanwu/public", tags=["public"])
public_router.include_router(general.router)
