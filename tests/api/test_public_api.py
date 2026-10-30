"""Public, unauthenticated surface: ping, time, version, configs."""

from httpx import AsyncClient

PUBLIC = "/api/v2/xuanwu/public"


async def test_ping(client: AsyncClient) -> None:
    resp = await client.get(f"{PUBLIC}/ping")
    assert resp.status_code == 200
    assert resp.json()["data"]["ping"] == "pong"


async def test_time(client: AsyncClient) -> None:
    resp = await client.get(f"{PUBLIC}/time")
    assert resp.status_code == 200
    assert "time" in resp.json()["data"]


async def test_version(client: AsyncClient) -> None:
    resp = await client.get(f"{PUBLIC}/version")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert {"version", "git_tag", "git_sha"} == set(data)


async def test_configs_are_client_safe(client: AsyncClient) -> None:
    resp = await client.get(f"{PUBLIC}/configs")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["password"]["min_length"] == 8
    assert data["captcha_provider"] == "none"
    # No secrets leak through the public config.
    assert "recaptcha_secret" not in data
