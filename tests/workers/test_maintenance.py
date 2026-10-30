"""`clean_expired_tokens` beat task — prunes orphaned refresh-jti references."""

import pytest
from app.workers import maintenance
from fakeredis import FakeStrictRedis


@pytest.fixture
def fake_sync_redis(monkeypatch: pytest.MonkeyPatch) -> FakeStrictRedis:
    client = FakeStrictRedis(decode_responses=True)
    monkeypatch.setattr(maintenance, "_redis_client", lambda: client)
    return client


def test_prunes_jtis_whose_token_key_expired(fake_sync_redis: FakeStrictRedis) -> None:
    # one live token, one orphaned reference (its refresh:* key has expired away)
    fake_sync_redis.set("refresh:live", "u1")
    fake_sync_redis.sadd("user:u1:refresh", "live", "orphan")

    removed = maintenance.clean_expired_tokens()

    assert removed == 1
    assert fake_sync_redis.smembers("user:u1:refresh") == {"live"}


def test_noop_when_all_references_live(fake_sync_redis: FakeStrictRedis) -> None:
    fake_sync_redis.set("refresh:a", "u1")
    fake_sync_redis.sadd("user:u1:refresh", "a")

    assert maintenance.clean_expired_tokens() == 0
    assert fake_sync_redis.smembers("user:u1:refresh") == {"a"}
