import pyotp
import redis.asyncio as redis
from app.services import totp
from app.services.totp import TOTPService


def test_secret_uri_and_qr() -> None:
    secret = totp.generate_secret()
    uri = totp.provisioning_uri(secret, "alice@example.com")
    assert "Xuanwu" in uri
    assert totp.qr_code_data_uri(uri).startswith("data:image/png;base64,")


async def test_verify_accepts_then_rejects_replay(fake_redis: redis.Redis) -> None:
    service = TOTPService(fake_redis)
    secret = totp.generate_secret()
    code = pyotp.TOTP(secret).now()
    assert await service.verify("u1", secret, code) is True  # first use accepted
    assert await service.verify("u1", secret, code) is False  # replay rejected


async def test_verify_rejects_wrong_code(fake_redis: redis.Redis) -> None:
    service = TOTPService(fake_redis)
    secret = totp.generate_secret()
    assert await service.verify("u1", secret, "000000") is False
