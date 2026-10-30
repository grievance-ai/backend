"""Uniform error handling.

Every error leaves the API as ``{"success": false, "errors": [...]}`` where each
entry is a dotted, translatable key (e.g. ``identity.session.invalid_params``).
Internal exception details are never leaked to the client.
"""

from collections.abc import Sequence
from typing import NoReturn

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.logging import get_logger

logger = get_logger(__name__)


class APIError(Exception):
    """An error with a fixed HTTP status and one or more i18n keys."""

    def __init__(self, keys: Sequence[str], status_code: int) -> None:
        self.keys: list[str] = list(keys)
        self.status_code = status_code
        super().__init__(", ".join(self.keys))


def _envelope(keys: Sequence[str]) -> dict[str, object]:
    return {"success": False, "errors": list(keys)}


# --- convenience raisers -----------------------------------------------------
def bad_request(*keys: str) -> NoReturn:
    raise APIError(keys, 400)


def unauthorized(*keys: str) -> NoReturn:
    raise APIError(keys, 401)


def forbidden(*keys: str) -> NoReturn:
    raise APIError(keys, 403)


def not_found(*keys: str) -> NoReturn:
    raise APIError(keys, 404)


def unprocessable(*keys: str) -> NoReturn:
    raise APIError(keys, 422)


# --- handler registration ----------------------------------------------------
def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def _api_error_handler(_request: Request, exc: APIError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=_envelope(exc.keys))

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        keys = [
            ".".join(str(part) for part in error["loc"][1:]) + f".{error['type']}"
            for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content=_envelope(keys))

    @app.exception_handler(Exception)
    async def _unhandled_handler(_request: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled_exception", exc_info=exc)
        return JSONResponse(status_code=500, content=_envelope(["server.internal_error"]))
