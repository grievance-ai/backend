"""Admin operations on users, permissions, and the audit log.

Ported from nebryx's admin routes. Filtering uses the query builders in
``app/queries``; label changes flow through the level engine so an admin
verifying a document (etc.) re-derives the user's level and state.
"""

import ipaddress
import uuid
from typing import TypeVar

import redis.asyncio as redis
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import restrictions as restrictions_engine
from app.core.authorize import invalidate_role_cache
from app.core.errors import APIError
from app.core.tokens import TokenService
from app.models.activity import Activity
from app.models.enums import (
    PermissionAction,
    RestrictionCategory,
    RestrictionScope,
    RestrictionState,
    UserState,
)
from app.models.permission import Permission
from app.models.restriction import Restriction
from app.models.user import User
from app.queries.activity_filter import ActivityFilter, build_activity_query, user_lookup_query
from app.queries.user_filter import UserFilter, build_user_query
from app.schemas.admin import (
    PermissionCreateIn,
    PermissionUpdateIn,
    RestrictionCreateIn,
    RestrictionUpdateIn,
)
from app.services import level_service

_Row = TypeVar("_Row")
_VALID_VERBS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "ALL"})
_VALID_ACTIONS = frozenset({a.value for a in PermissionAction})
_VALID_CATEGORIES = frozenset({c.value for c in RestrictionCategory})
_VALID_SCOPES = frozenset({s.value for s in RestrictionScope})
_LOCKING_STATES = frozenset(
    {UserState.banned.value, UserState.locked.value, UserState.deleted.value}
)


async def _paginate(
    db: AsyncSession, stmt: Select[tuple[_Row]], *, page: int, limit: int
) -> tuple[list[_Row], int]:
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = await db.scalars(stmt.limit(limit).offset((page - 1) * limit))
    return list(rows.all()), int(total)


# --- users -------------------------------------------------------------------
async def list_users(
    db: AsyncSession, f: UserFilter, *, page: int, limit: int
) -> tuple[list[User], int]:
    return await _paginate(db, build_user_query(f), page=page, limit=limit)


async def get_user(db: AsyncSession, uid: str) -> User:
    user = await db.scalar(select(User).options(selectinload(User.labels)).where(User.uid == uid))
    if user is None:
        raise APIError(["admin.user.not_found"], 404)
    return user


async def _require_user(db: AsyncSession, uid: str) -> User:
    user = await db.scalar(select(User).where(User.uid == uid))
    if user is None:
        raise APIError(["admin.user.not_found"], 404)
    return user


async def set_state(db: AsyncSession, redis_client: redis.Redis, *, uid: str, state: str) -> User:
    user = await _require_user(db, uid)
    user.state = state
    await db.commit()
    await db.refresh(user)
    if state in _LOCKING_STATES:
        await TokenService(redis_client).invalidate_all(str(user.id))
    return user


async def set_role(db: AsyncSession, *, uid: str, role: str) -> User:
    user = await _require_user(db, uid)
    if user.role == role:
        raise APIError(["admin.user.role_no_change"], 422)
    user.role = role
    await db.commit()
    await db.refresh(user)
    return user


async def disable_otp(db: AsyncSession, redis_client: redis.Redis, *, uid: str, otp: bool) -> User:
    if otp:
        raise APIError(["admin.user.otp_enable_forbidden"], 422)  # admins may only disable
    user = await _require_user(db, uid)
    user.otp = False
    user.otp_secret = None
    await db.commit()
    # Drop any otp label and force re-login without 2FA.
    await level_service.remove_label(db, user, key="otp", redis_client=redis_client)
    await TokenService(redis_client).invalidate_all(str(user.id))
    await db.refresh(user)
    return user


async def add_user_label(
    db: AsyncSession, redis_client: redis.Redis, *, uid: str, key: str, value: str, scope: str
) -> User:
    user = await _require_user(db, uid)
    await level_service.add_label(
        db, user, key=key, value=value, scope=scope, redis_client=redis_client
    )
    return user


async def remove_user_label(
    db: AsyncSession, redis_client: redis.Redis, *, uid: str, key: str, scope: str
) -> User:
    user = await _require_user(db, uid)
    await level_service.remove_label(db, user, key=key, scope=scope, redis_client=redis_client)
    return user


# --- permissions -------------------------------------------------------------
async def list_permissions(
    db: AsyncSession, *, page: int, limit: int
) -> tuple[list[Permission], int]:
    stmt = select(Permission).order_by(Permission.created_at.asc())
    return await _paginate(db, stmt, page=page, limit=limit)


def _normalize_permission(verb: str, action: str) -> tuple[str, str]:
    upper_verb, upper_action = verb.upper(), action.upper()
    if upper_verb not in _VALID_VERBS:
        raise APIError(["admin.permissions.invalid_verb"], 422)
    if upper_action not in _VALID_ACTIONS:
        raise APIError(["admin.permissions.invalid_action"], 422)
    return upper_verb, upper_action


async def create_permission(
    db: AsyncSession, redis_client: redis.Redis, data: PermissionCreateIn
) -> Permission:
    verb, action = _normalize_permission(data.verb, data.action)
    existing = await db.scalar(
        select(Permission).where(
            Permission.role == data.role, Permission.verb == verb, Permission.path == data.path
        )
    )
    if existing is not None:
        raise APIError(["admin.permissions.exists"], 409)
    permission = Permission(
        role=data.role, verb=verb, path=data.path, action=action, topic=data.topic
    )
    db.add(permission)
    await db.commit()
    await db.refresh(permission)
    await invalidate_role_cache(redis_client, data.role)
    return permission


async def update_permission(
    db: AsyncSession, redis_client: redis.Redis, permission_id: uuid.UUID, data: PermissionUpdateIn
) -> Permission:
    permission = await db.get(Permission, permission_id)
    if permission is None:
        raise APIError(["admin.permissions.not_found"], 404)
    roles_to_bust = {permission.role}

    if data.verb is not None or data.action is not None:
        verb, action = _normalize_permission(
            data.verb or permission.verb, data.action or permission.action
        )
        permission.verb, permission.action = verb, action
    if data.role is not None:
        permission.role = data.role
        roles_to_bust.add(data.role)
    if data.path is not None:
        permission.path = data.path
    if data.topic is not None:
        permission.topic = data.topic

    await db.commit()
    await db.refresh(permission)
    for role in roles_to_bust:
        await invalidate_role_cache(redis_client, role)
    return permission


async def delete_permission(
    db: AsyncSession, redis_client: redis.Redis, permission_id: uuid.UUID
) -> None:
    permission = await db.get(Permission, permission_id)
    if permission is None:
        raise APIError(["admin.permissions.not_found"], 404)
    role = permission.role
    await db.delete(permission)
    await db.commit()
    await invalidate_role_cache(redis_client, role)


# --- activities --------------------------------------------------------------
async def list_activities(
    db: AsyncSession, f: ActivityFilter, *, page: int, limit: int
) -> tuple[list[Activity], int]:
    if f.uid or f.email:
        users = (await db.scalars(user_lookup_query(f.uid, f.email))).all()
        f = ActivityFilter(
            action=f.action,
            topic=f.topic,
            user_ids=[u.id for u in users] or [uuid.uuid4()],  # no match → empty result
            date_from=f.date_from,
            date_to=f.date_to,
        )
    return await _paginate(db, build_activity_query(f), page=page, limit=limit)


# --- restrictions ------------------------------------------------------------
def _validate_restriction(category: str, scope: str, value: str) -> None:
    if category not in _VALID_CATEGORIES:
        raise APIError(["admin.restriction.invalid_category"], 422)
    if scope not in _VALID_SCOPES:
        raise APIError(["admin.restriction.invalid_scope"], 422)
    try:
        if scope == RestrictionScope.ip.value:
            ipaddress.ip_address(value)
        elif scope == RestrictionScope.ip_subnet.value:
            ipaddress.ip_network(value, strict=False)
    except ValueError as exc:
        raise APIError(["admin.restriction.invalid_value"], 422) from exc


async def list_restrictions(
    db: AsyncSession, *, page: int, limit: int
) -> tuple[list[Restriction], int]:
    stmt = select(Restriction).order_by(Restriction.created_at.asc())
    return await _paginate(db, stmt, page=page, limit=limit)


async def create_restriction(
    db: AsyncSession, redis_client: redis.Redis, data: RestrictionCreateIn
) -> Restriction:
    _validate_restriction(data.category, data.scope, data.value)
    restriction = Restriction(
        category=data.category,
        scope=data.scope,
        value=data.value,
        code=restrictions_engine.assign_code(data.category, data.scope, data.code),
        state=data.state,
    )
    db.add(restriction)
    await db.commit()
    await db.refresh(restriction)
    await restrictions_engine.invalidate_cache(redis_client)
    return restriction


async def update_restriction(
    db: AsyncSession,
    redis_client: redis.Redis,
    restriction_id: uuid.UUID,
    data: RestrictionUpdateIn,
) -> Restriction:
    restriction = await db.get(Restriction, restriction_id)
    if restriction is None:
        raise APIError(["admin.restriction.not_found"], 404)
    if data.value is not None:
        _validate_restriction(restriction.category, restriction.scope, data.value)
        restriction.value = data.value
    if data.code is not None:
        restriction.code = data.code
    if data.state is not None:
        if data.state not in {s.value for s in RestrictionState}:
            raise APIError(["admin.restriction.invalid_state"], 422)
        restriction.state = data.state
    await db.commit()
    await db.refresh(restriction)
    await restrictions_engine.invalidate_cache(redis_client)
    return restriction


async def delete_restriction(
    db: AsyncSession, redis_client: redis.Redis, restriction_id: uuid.UUID
) -> None:
    restriction = await db.get(Restriction, restriction_id)
    if restriction is None:
        raise APIError(["admin.restriction.not_found"], 404)
    await db.delete(restriction)
    await db.commit()
    await restrictions_engine.invalidate_cache(redis_client)
