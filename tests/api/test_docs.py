"""Role-aware API docs: /admin/* is visible in the schema only to admins."""

from typing import Any

from httpx import AsyncClient

from tests.conftest import LoginAs

ADMIN_PREFIX = "/api/v2/xuanwu/admin"


def _has_admin_paths(schema: dict[str, Any]) -> bool:
    return any(path.startswith(ADMIN_PREFIX) for path in schema["paths"])


async def test_anonymous_schema_hides_admin(client: AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).json()
    assert not _has_admin_paths(schema)
    # Public surface is still present.
    assert any(p.startswith("/api/v2/xuanwu/identity") for p in schema["paths"])


async def test_member_schema_hides_admin(client: AsyncClient, login_as: LoginAs) -> None:
    await login_as(role="member")
    schema = (await client.get("/openapi.json")).json()
    assert not _has_admin_paths(schema)


async def test_admin_schema_includes_admin(client: AsyncClient, login_as: LoginAs) -> None:
    await login_as(role="admin")
    schema = (await client.get("/openapi.json")).json()
    assert _has_admin_paths(schema)


async def test_docs_page_renders(client: AsyncClient) -> None:
    resp = await client.get("/docs")
    assert resp.status_code == 200
    assert "swagger-ui" in resp.text.lower()


async def test_redoc_page_renders(client: AsyncClient) -> None:
    resp = await client.get("/redoc")
    assert resp.status_code == 200
    assert "redoc" in resp.text.lower()


async def test_schema_documents_security_schemes(client: AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).json()
    schemes = schema["components"]["securitySchemes"]
    assert {"AccessCookie", "BearerAuth", "CsrfToken", "ApiKeyId"} <= set(schemes)
    assert schemes["AccessCookie"]["in"] == "cookie"
    assert schemes["ApiKeyId"]["name"] == "X-Auth-Apikey"


async def test_schema_has_tag_descriptions(client: AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).json()
    tags = {tag["name"]: tag.get("description", "") for tag in schema["tags"]}
    assert tags.get("public")
    assert tags.get("identity")
