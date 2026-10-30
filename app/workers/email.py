"""Celery task that renders and delivers a branded transactional email.

Takes an event key + data (not a rendered message) so a retry re-renders from
the registry. Delivery uses the configured provider; transient failures are
retried up to three times, five minutes apart.
"""

from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.emails import render_event
from app.integrations.email import EmailMessage, get_provider
from app.workers.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(  # type: ignore[untyped-decorator]
    name="email.send", bind=True, max_retries=3, default_retry_delay=300
)
def send_email(
    self: Any,
    *,
    event_key: str,
    to: str,
    data: dict[str, Any],
    language: str | None = None,
) -> None:
    rendered = render_event(event_key, language or settings.email_default_language, data)
    message = EmailMessage(
        to=to,
        subject=rendered.subject,
        html=rendered.html,
        text=rendered.text,
        from_email=settings.email_from,
        from_name=settings.email_from_name,
    )
    try:
        get_provider().send(message)
    except Exception as exc:
        logger.warning("email_send_failed", to=to, event_key=event_key, exc_info=True)
        raise self.retry(exc=exc) from exc
    logger.info("email_sent", to=to, event_key=event_key)
