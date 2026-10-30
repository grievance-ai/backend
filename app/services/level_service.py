"""Progressive-verification engine — a port of Barong's User#update_level and
User#update_state (exchange_auth/app/models/user.rb) plus its barong.yml
``activation_requirements`` / ``state_triggers``.

Labels are the raw events ("email=verified", "ban=true"). This module is the
single place that derives a user's numeric ``level`` (from the ``levels`` table)
and account ``state`` (from ``config/auth.yml``) out of the *private* labels they
hold. Barong runs this from ``after_commit`` callbacks on Label; we call it
explicitly from the services that mutate labels (ARCHITECTURE §3.1 — no hidden
ORM callbacks), but the algorithm matches Barong exactly.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any

import redis.asyncio as redis
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.tokens import TokenService
from app.models.enums import LabelScope, UserState
from app.models.label import Label
from app.models.level import Level
from app.models.user import User

# System labels live in the private scope; public labels never affect level/state.
SYSTEM_SCOPE = LabelScope.private.value
# States that block authentication → revoke the user's active sessions.
_LOCKING_STATES = frozenset(
    {UserState.banned.value, UserState.locked.value, UserState.deleted.value}
)


@lru_cache
def _auth_config() -> dict[str, Any]:
    path = Path(settings.auth_config_path)
    if not path.exists():
        return {}
    data: dict[str, Any] = yaml.safe_load(path.read_text()) or {}
    return data


def activation_requirements() -> dict[str, str]:
    reqs = _auth_config().get("activation_requirements") or {}
    return {str(k): str(v) for k, v in reqs.items()}


def state_triggers() -> dict[str, list[str]]:
    triggers = _auth_config().get("state_triggers") or {}
    return {str(state): [str(p) for p in prefixes] for state, prefixes in triggers.items()}


async def _private_labels(db: AsyncSession, user_id: object) -> dict[str, str]:
    """The user's private labels as a ``{key: value}`` hash (key is unique per
    user within the private scope)."""
    rows = await db.scalars(
        select(Label).where(Label.user_id == user_id, Label.scope == SYSTEM_SCOPE)
    )
    return {row.key: row.value for row in rows.all()}


async def recompute_level(db: AsyncSession, user: User, labels: dict[str, str]) -> None:
    """Port of ``User#update_level``: the level is the id of the highest ``levels``
    row whose ``key:value`` the user holds — not necessarily contiguous."""
    tags = {f"{key}:{value}" for key, value in labels.items()}
    user_level = 0
    for level in (await db.scalars(select(Level).order_by(Level.id))).all():
        if f"{level.key}:{level.value}" in tags:
            user_level = level.id
    user.level = user_level


async def recompute_state(db: AsyncSession, user: User, labels: dict[str, str]) -> bool:
    """Port of ``User#update_state``: default ``pending``; ``active`` when the
    activation requirements are a subset of the user's labels; then state
    triggers override by label-key prefix (last match wins). Returns ``True`` when
    the resulting state locks the account so the caller can revoke sessions."""
    resulting = UserState.pending.value
    requirements = activation_requirements()
    if all(labels.get(key) == value for key, value in requirements.items()):
        resulting = UserState.active.value

    for state, prefixes in state_triggers().items():
        for prefix in prefixes:
            if any(key.startswith(prefix) for key in labels):
                resulting = state

    user.state = resulting
    return resulting in _LOCKING_STATES


async def _sync(db: AsyncSession, user: User, redis_client: redis.Redis | None) -> None:
    """Flush the pending label change, re-derive level + state, persist, revoke."""
    await db.flush()  # make the label add/remove visible to the recompute queries
    labels = await _private_labels(db, user.id)
    await recompute_level(db, user, labels)
    locked = await recompute_state(db, user, labels)
    await db.commit()
    await db.refresh(user)
    if locked and redis_client is not None:
        await TokenService(redis_client).invalidate_all(str(user.id))


async def add_label(
    db: AsyncSession,
    user: User,
    *,
    key: str,
    value: str = "verified",
    scope: str = SYSTEM_SCOPE,
    redis_client: redis.Redis | None = None,
) -> Label:
    """Add or update a label, then re-derive level and state for private labels.

    Idempotent on ``(user, key, scope)``: an existing label's value is updated in
    place. Only private labels affect level/state; public ones just persist.
    """
    label = await db.scalar(
        select(Label).where(Label.user_id == user.id, Label.key == key, Label.scope == scope)
    )
    if label is None:
        label = Label(user_id=user.id, key=key, value=value, scope=scope)
        db.add(label)
    else:
        label.value = value
    if scope == SYSTEM_SCOPE:
        await _sync(db, user, redis_client)
    else:
        await db.commit()
        await db.refresh(label)
    return label


async def remove_label(
    db: AsyncSession,
    user: User,
    *,
    key: str,
    scope: str = SYSTEM_SCOPE,
    redis_client: redis.Redis | None = None,
) -> None:
    """Remove a label (if present), then re-derive level and state for private ones."""
    label = await db.scalar(
        select(Label).where(Label.user_id == user.id, Label.key == key, Label.scope == scope)
    )
    if label is not None:
        await db.delete(label)
    if scope == SYSTEM_SCOPE:
        await _sync(db, user, redis_client)
    else:
        await db.commit()
