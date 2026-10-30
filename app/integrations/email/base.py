"""Email provider interface shared by every concrete provider."""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    html: str
    text: str
    from_email: str
    from_name: str


@runtime_checkable
class EmailProvider(Protocol):
    """Sends a single message. Implementations raise on transient failure so the
    Celery task can retry."""

    def send(self, message: EmailMessage) -> None: ...
