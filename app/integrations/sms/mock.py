"""In-memory SMS provider for development and tests.

Captured messages are appended to :data:`outbox`; tests assert against it and
call :func:`clear` between cases.
"""

from app.core.logging import get_logger
from app.integrations.sms.base import SMSMessage, SMSProvider, verification_body

logger = get_logger(__name__)

outbox: list[SMSMessage] = []


def clear() -> None:
    outbox.clear()


class MockSMSProvider(SMSProvider):
    def send_code(self, *, number: str, code: str | None) -> None:
        body = verification_body(code) if code else "verification initiated"
        outbox.append(SMSMessage(to=number, body=body))
        logger.info("sms_sent_mock", to=number)
