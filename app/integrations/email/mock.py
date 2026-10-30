"""In-memory email provider for development and tests.

Captured messages are appended to :data:`outbox`; tests assert against it and
call :func:`clear` between cases.
"""

from app.core.logging import get_logger
from app.integrations.email.base import EmailMessage

logger = get_logger(__name__)

outbox: list[EmailMessage] = []


def clear() -> None:
    outbox.clear()


class MockEmailProvider:
    def send(self, message: EmailMessage) -> None:
        outbox.append(message)
        logger.info("email_sent_mock", to=message.to, subject=message.subject)
