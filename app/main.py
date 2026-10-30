"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.docs import setup_docs
from app.api.v2.public.router import public_router
from app.api.v2.router import api_router
from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.ratelimit import limiter, rate_limit_handler
from app.core.redis import check_redis
from app.db.session import check_database

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-XSS-Protection": "0",
}

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    logger.info(
        "startup",
        app_env=settings.app_env,
        database=await check_database(),
        redis=await check_redis(),
    )
    yield


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(
        title="Xuanwu Auth",
        version="0.1.0",
        description="Standalone authentication & authorization server.",
        lifespan=lifespan,
        # Defaults are disabled and replaced by the role-aware docs below, so
        # /admin/* only appears in the schema for a logged-in admin.
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Per-IP rate limiting (slowapi) shared across workers via Redis.
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
    app.add_middleware(SlowAPIMiddleware)

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Response:
        response: Response = await call_next(request)
        for header, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        if settings.hsts_enabled:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=63072000; includeSubDomains"
            )
        return response

    register_exception_handlers(app)
    # Public router is mounted before (and outside) the restriction-guarded
    # api_router so health checks survive maintenance mode.
    app.include_router(public_router)
    app.include_router(api_router)
    setup_docs(app)

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    async def readiness() -> dict[str, object]:
        database_ok = await check_database()
        redis_ok = await check_redis()
        return {
            "status": "ok" if database_ok and redis_ok else "degraded",
            "database": database_ok,
            "redis": redis_ok,
        }

    return app


app = create_app()
