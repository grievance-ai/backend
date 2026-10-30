"""IP / geo access restrictions — a port of Barong's AuthorizeController restriction
logic (exchange_auth/app/controllers/authorize_controller.rb + Restriction model).

Enabled restrictions are grouped ``category -> scope -> [(value, code)]`` and
cached for five minutes. On each request the categories are checked in priority
order: a matching ``whitelist`` short-circuits and allows the request; a matching
``blacklist`` or ``maintenance`` denies it with the restriction's status code
(maintenance is 471); ``blocklogin`` denies only the login endpoint.
"""

import ipaddress
import json
from typing import Any

import redis.asyncio as redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import HTTPConnection

from app.core.errors import APIError
from app.integrations import geoip
from app.models.enums import RestrictionState
from app.models.restriction import Restriction

# Category priority (whitelist wins first); scope precedence (most precise first).
CATEGORIES = ("whitelist", "maintenance", "blacklist", "blocklogin")
SCOPES = ("all", "ip", "ip_subnet", "continent", "country")
DEFAULT_CODES = {"continent": 423, "country": 423, "ip_subnet": 403, "ip": 401, "all": 401}
MAINTENANCE_CODE = 471

_CACHE_KEY = "restrictions:table"
_CACHE_TTL = 300
_DENY_CATEGORIES = frozenset({"blacklist", "maintenance"})
_LOGIN_SUFFIX = "/identity/sessions"

# Grouped table: {category: {scope: [[value, code], ...]}}
RestrictionTable = dict[str, dict[str, list[list[Any]]]]


def assign_code(category: str, scope: str, code: int | None) -> int | None:
    """Resolve a restriction's status code (Barong Restriction#assign_code)."""
    if category == "whitelist":
        return None
    if code:
        return code
    if category == "maintenance":
        return MAINTENANCE_CODE
    return DEFAULT_CODES.get(scope, 401)


def _empty_table() -> RestrictionTable:
    return {c: {s: [] for s in SCOPES} for c in CATEGORIES}


async def _load_table(db: AsyncSession) -> RestrictionTable:
    rows = (
        await db.scalars(
            select(Restriction).where(Restriction.state == RestrictionState.enabled.value)
        )
    ).all()
    table = _empty_table()
    for r in rows:
        if r.category in table and r.scope in table[r.category]:
            table[r.category][r.scope].append([r.value, r.code])
    return table


async def _fetch_table(redis_client: redis.Redis, db: AsyncSession | None) -> RestrictionTable:
    cached = await redis_client.get(_CACHE_KEY)
    if cached is not None:
        return json.loads(cached)  # type: ignore[no-any-return]
    if db is None:  # no session available (e.g. unit tests with a seeded cache)
        return _empty_table()
    table = await _load_table(db)
    await redis_client.setex(_CACHE_KEY, _CACHE_TTL, json.dumps(table))
    return table


async def invalidate_cache(redis_client: redis.Redis) -> None:
    await redis_client.delete(_CACHE_KEY)


def _ip_in(value: str, ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip) in ipaddress.ip_network(value, strict=False)
    except ValueError:
        return False


def _first_match(
    table: RestrictionTable, category: str, *, ip: str, country: str | None, continent: str | None
) -> list[Any] | None:
    """Most precise match: all → ip → ip_subnet → continent → country."""
    scopes = table.get(category, {})
    if scopes.get("all"):
        return scopes["all"][0]
    for value, code in scopes.get("ip", []):
        if value == ip:
            return [value, code]
    for value, code in scopes.get("ip_subnet", []):
        if _ip_in(value, ip):
            return [value, code]
    if continent:
        for value, code in scopes.get("continent", []):
            if value.casefold() == continent.casefold():
                return [value, code]
    if country:
        for value, code in scopes.get("country", []):
            if value.casefold() == country.casefold():
                return [value, code]
    return None


async def evaluate(
    request: HTTPConnection, redis_client: redis.Redis, db: AsyncSession | None = None
) -> None:
    """Raise ``APIError`` (with the restriction's status code) when the request is
    blocked. A whitelist match allows the request through unconditionally."""
    table = await _fetch_table(redis_client, db)
    ip = request.client.host if request.client else ""
    country = geoip.resolve_country(ip)
    continent = None  # continent resolution requires a richer GeoIP provider
    # HTTPConnection also covers WebSockets, which have no method.
    method = getattr(request, "method", "GET")
    is_login = method == "POST" and request.url.path.endswith(_LOGIN_SUFFIX)

    for category in CATEGORIES:
        match = _first_match(table, category, ip=ip, country=country, continent=continent)
        if match is None:
            continue
        if category == "whitelist":
            return  # explicitly allowed; skip the remaining categories
        if category in _DENY_CATEGORIES or (category == "blocklogin" and is_login):
            raise APIError([f"authz.restrict.{category}"], int(match[1]))
