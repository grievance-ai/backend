"""Celery task that delivers a phone verification code via the configured
provider. (The matching verify step is synchronous and lives in the phone
service, since the request needs the result immediately.)

Transient failures are retried up to three times, five minutes apart.
"""

from typing import Any

from app.core.logging import get_logger
from app.integrations.sms import get_provider
from app.workers.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(  # type: ignore[untyped-decorator]
    name="sms.send_code", bind=True, max_retries=3, default_retry_delay=300
)
def send_verification_code(self: Any, *, number: str, code: str | None) -> None:
    try:
        get_provider().send_code(number=number, code=code)
    except Exception as exc:
        logger.warning("sms_send_failed", to=number, exc_info=True)
        raise self.retry(exc=exc) from exc
    logger.info("sms_code_sent", to=number)
