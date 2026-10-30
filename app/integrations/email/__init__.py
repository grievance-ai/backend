"""Email provider selection.

``get_provider()`` returns the provider named by ``EMAIL_PROVIDER``. The default
``mock`` keeps development and tests offline; ``smtp`` and ``sendgrid`` are the
real backends.
"""

from app.core.config import settings
from app.integrations.email.base import EmailMessage, EmailProvider
from app.integrations.email.mock import MockEmailProvider
from app.integrations.email.sendgrid_provider import SendGridEmailProvider
from app.integrations.email.smtp import SMTPEmailProvider

__all__ = ["EmailMessage", "EmailProvider", "get_provider"]


def get_provider() -> EmailProvider:
    provider = settings.email_provider.lower()
    if provider == "smtp":
        return SMTPEmailProvider()
    if provider == "sendgrid":
        return SendGridEmailProvider()
    return MockEmailProvider()
