from app.core.errors import APIError, not_found, register_exception_handlers
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def _build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/missing")
    async def missing() -> dict[str, str]:
        not_found("resource.thing.not_found")

    @app.get("/multi")
    async def multi() -> dict[str, str]:
        raise APIError(["a.b.c", "d.e.f"], 422)

    return app


async def _get(path: str) -> tuple[int, object]:
    transport = ASGITransport(app=_build_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(path)
    return resp.status_code, resp.json()


async def test_single_key_envelope() -> None:
    status, body = await _get("/missing")
    assert status == 404
    assert body == {"success": False, "errors": ["resource.thing.not_found"]}


async def test_multiple_key_envelope() -> None:
    status, body = await _get("/multi")
    assert status == 422
    assert body == {"success": False, "errors": ["a.b.c", "d.e.f"]}
