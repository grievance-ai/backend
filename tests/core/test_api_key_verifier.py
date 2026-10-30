import time

import redis.asyncio as redis
from app.services.api_key_verifier import APIKeyVerifier, expected_signature


def _now_ms() -> str:
    return str(int(time.time() * 1000))


async def test_valid_signature_then_replay(fake_redis: redis.Redis) -> None:
    verifier = APIKeyVerifier(fake_redis)
    kid, secret, nonce = "kid1", "s3cr3t", _now_ms()
    signature = expected_signature(secret, nonce, kid)
    assert await verifier.verify(kid=kid, nonce=nonce, signature=signature, secret=secret) is True
    assert await verifier.verify(kid=kid, nonce=nonce, signature=signature, secret=secret) is False


async def test_bad_signature_rejected(fake_redis: redis.Redis) -> None:
    verifier = APIKeyVerifier(fake_redis)
    nonce = _now_ms()
    assert (
        await verifier.verify(kid="kid1", nonce=nonce, signature="deadbeef", secret="s3cr3t")
        is False
    )


async def test_stale_nonce_rejected(fake_redis: redis.Redis) -> None:
    verifier = APIKeyVerifier(fake_redis)
    kid, secret = "kid1", "s3cr3t"
    nonce = str(int(time.time() * 1000) - 999_999)  # ~1000s in the past
    signature = expected_signature(secret, nonce, kid)
    assert await verifier.verify(kid=kid, nonce=nonce, signature=signature, secret=secret) is False
