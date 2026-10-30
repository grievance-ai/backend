"""Typed helpers that enqueue branded emails by event key.

Services and routers call these instead of touching the Celery task directly, so
the event keys, link construction, and data shape live in one place.
"""

from app.core.config import settings
from app.models.user import User
from app.workers.email import send_email


def send_confirmation_email(user: User, token: str) -> None:
    url = f"{settings.frontend_url}/confirm-email?token={token}"
    send_email.delay(event_key="email_confirmation", to=user.email, data={"confirmation_url": url})


def send_password_reset_email(user: User, token: str) -> None:
    url = f"{settings.frontend_url}/reset-password?token={token}"
    send_email.delay(event_key="password_reset", to=user.email, data={"reset_url": url})


def send_session_create_email(user: User, *, ip: str | None, user_agent: str | None) -> None:
    send_email.delay(
        event_key="session_create",
        to=user.email,
        data={"ip": ip, "user_agent": user_agent},
    )


def send_label_email(user: User, *, key: str, value: str) -> None:
    send_email.delay(
        event_key="label",
        to=user.email,
        data={"label_key": key, "label_value": value},
    )
