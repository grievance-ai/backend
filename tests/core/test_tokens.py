import pytest
import redis.asyncio as redis
from app.core import security
from app.core.errors import APIError
from app.core.tokens import TokenService


async def test_issue_pair_returns_valid_tokens(fake_redis: redis.Redis) -> None:
    service = TokenService(fake_redis)
    pair = await service.issue_pair(user_id="u1", role="member")
    assert pair.access_token and pair.refresh_token and pair.csrf_token
    access = security.decode_token(pair.access_token, expected_type=security.ACCESS_TYPE)
    assert access["uid"] == "u1"


async def test_rotate_issues_new_and_revokes_old(fake_redis: redis.Redis) -> None:
    service = TokenService(fake_redis)
    pair = await service.issue_pair(user_id="u1", role="member")
    rotated = await service.rotate(pair.refresh_token)
    assert rotated.refresh_token != pair.refresh_token
    # the old refresh token is now invalid
    with pytest.raises(APIError):
        await service.rotate(pair.refresh_token)


async def test_invalidate_all_revokes_every_session(fake_redis: redis.Redis) -> None:
    service = TokenService(fake_redis)
    first = await service.issue_pair(user_id="u2", role="member")
    second = await service.issue_pair(user_id="u2", role="member")
    await service.invalidate_all("u2")
    for pair in (first, second):
        with pytest.raises(APIError):
            await service.rotate(pair.refresh_token)


async def test_revoke_single_session(fake_redis: redis.Redis) -> None:
    service = TokenService(fake_redis)
    pair = await service.issue_pair(user_id="u3", role="member")
    payload = security.decode_token(pair.refresh_token, expected_type=security.REFRESH_TYPE)
    await service.revoke(payload["jti"], "u3")
    with pytest.raises(APIError):
        await service.rotate(pair.refresh_token)
