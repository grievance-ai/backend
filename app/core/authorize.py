"""Role-based authorization.

Access is decided by the ``Permission`` table (role x HTTP verb x path-prefix x
action). A coarse ``authz_rules.yml`` allow/deny list is consulted first. The
per-role permission set is cached in Redis to avoid a query per request.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import TypedDict, cast

import redis.asyncio as redis
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import APIError
from app.models.enums import PermissionAction
from app.models.permission import Permission

ALL_VERB = "ALL"


class PermRow(TypedDict):
    verb: str
    path: str
    action: str
    topic: str | None


@lru_cache
def load_authz_rules() -> dict[str, list[str]]:
    path = Path(settings.authz_rules_path)
    if not path.exists():
        return {"pass": [], "block": []}
    data = yaml.safe_load(path.read_text()) or {}
    return {
        "pass": [str(prefix) for prefix in (data.get("pass") or [])],
        "block": [str(prefix) for prefix in (data.get("block") or [])],
    }


def _cache_key(role: str) -> str:
    return f"permissions:{role}"


async def invalidate_role_cache(redis_client: redis.Redis, role: str) -> None:
    await redis_client.delete(_cache_key(role))


async def _permissions_for_role(
    db: AsyncSession, redis_client: redis.Redis, role: str
) -> list[PermRow]:
    cached = await redis_client.get(_cache_key(role))
    if cached is not None:
        return cast("list[PermRow]", json.loads(cached))
    rows = (await db.scalars(select(Permission).where(Permission.role == role))).all()
    perms: list[PermRow] = [
        {"verb": row.verb, "path": row.path, "action": row.action, "topic": row.topic}
        for row in rows
    ]
    await redis_client.setex(_cache_key(role), settings.permission_cache_ttl, json.dumps(perms))
    return perms


async def authorize(
    db: AsyncSession, redis_client: redis.Redis, *, role: str, method: str, path: str
) -> list[str]:
    """Authorize a request; raise ``APIError(403)`` if denied, else return audit topics."""
    rules = load_authz_rules()
    if any(path.startswith(prefix) for prefix in rules["block"]):
        raise APIError(["authz.blocked"], 403)
    if any(path.startswith(prefix) for prefix in rules["pass"]):
        return []

    perms = await _permissions_for_role(db, redis_client, role)
    matched = [p for p in perms if p["verb"] in (method, ALL_VERB) and path.startswith(p["path"])]

    if any(p["action"] == PermissionAction.drop.value for p in matched):
        raise APIError(["authz.forbidden"], 403)
    if not any(p["action"] == PermissionAction.accept.value for p in matched):
        raise APIError(["authz.forbidden"], 403)

    topics: list[str] = []
    for p in matched:
        if p["action"] == PermissionAction.audit.value and p["topic"] is not None:
            topics.append(p["topic"])
    return topics
