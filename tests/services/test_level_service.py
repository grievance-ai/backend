"""Progressive-verification engine — ported from Barong's update_level/update_state.

Level is the highest matched tier (NOT contiguous); state is recomputed from
activation requirements plus key-prefix state triggers.
"""

import uuid

import redis.asyncio as redis
from app.core.tokens import TokenService
from app.models.enums import UserState
from app.models.user import User
from app.services import level_service
from sqlalchemy.ext.asyncio import AsyncSession


def test_auth_config_loaded() -> None:
    """The config ships Barong's activation requirements and state triggers."""
    assert level_service.activation_requirements() == {"email": "verified"}
    triggers = level_service.state_triggers()
    assert "ban" in triggers["banned"]
    assert "lock" in triggers["locked"]
    assert "delete" in triggers["deleted"]


async def _make_user(db: AsyncSession) -> User:
    user = User(email=f"u{uuid.uuid4().hex[:12]}@example.com", password_digest="x")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def test_email_label_activates_and_reaches_level_1(db: AsyncSession) -> None:
    user = await _make_user(db)
    assert user.level == 0
    assert user.state == UserState.pending.value

    await level_service.add_label(db, user, key="email", value="verified")

    assert user.level == 1
    assert user.state == UserState.active.value


async def test_level_is_highest_matched_not_contiguous(db: AsyncSession) -> None:
    """Barong's update_level: email (1) + document (3) but no phone (2) → level 3."""
    user = await _make_user(db)
    await level_service.add_label(db, user, key="email", value="verified")
    await level_service.add_label(db, user, key="document", value="verified")
    assert user.level == 3  # not 1 — the gap at phone does not stop progression


async def test_removing_email_drops_level_and_deactivates(db: AsyncSession) -> None:
    user = await _make_user(db)
    await level_service.add_label(db, user, key="email", value="verified")
    assert user.level == 1 and user.state == UserState.active.value

    await level_service.remove_label(db, user, key="email")
    assert user.level == 0
    assert user.state == UserState.pending.value  # activation requirement gone


async def test_ban_prefix_label_locks_and_revokes_sessions(
    db: AsyncSession, fake_redis: redis.Redis
) -> None:
    user = await _make_user(db)
    tokens = TokenService(fake_redis)
    await tokens.issue_pair(user_id=str(user.id), role=user.role)
    assert await fake_redis.smembers(f"user:{user.id}:refresh")  # type: ignore[misc]

    # Any private label whose key starts with "ban" triggers the banned state.
    await level_service.add_label(db, user, key="ban", value="true", redis_client=fake_redis)

    assert user.state == UserState.banned.value
    assert not await fake_redis.smembers(f"user:{user.id}:refresh")  # type: ignore[misc]


async def test_lock_prefix_label_sets_locked_state(db: AsyncSession) -> None:
    user = await _make_user(db)
    await level_service.add_label(db, user, key="email", value="verified")
    assert user.state == UserState.active.value

    # "suspicious" is a locked-state trigger prefix.
    await level_service.add_label(db, user, key="suspicious-activity", value="flagged")
    assert user.state == UserState.locked.value

    await level_service.remove_label(db, user, key="suspicious-activity")
    assert user.state == UserState.active.value  # email still verified
