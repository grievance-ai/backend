"""SMS provider interface — ported from nebryx's src/services/sms.

Each provider both *delivers* a verification code and *checks* one, because the
two paradigms differ: self-managed providers (mock, Twilio SMS, AWS SNS) send a
code we generated and verify by comparing it; Twilio Verify issues and checks
the code itself. ``manages_codes`` tells the phone service which paradigm is
active (so it knows whether to generate and store a code at all).
"""

import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.core.config import settings


@dataclass(frozen=True)
class SMSMessage:
    to: str  # destination number in E.164 form
    body: str


def verification_body(code: str) -> str:
    return settings.sms_content_template.format(code=code)


class SMSProvider(ABC):
    # True only for providers that issue and validate the code themselves
    # (Twilio Verify); self-managed providers leave this False.
    manages_codes: bool = False

    @abstractmethod
    def send_code(self, *, number: str, code: str | None) -> None:
        """Deliver a verification code. Self-managed providers send ``code``;
        Twilio Verify ignores it and triggers its own."""

    def check_code(self, *, number: str, code: str, expected: str | None) -> bool:
        """Default (self-managed): constant-time compare against the stored code."""
        return expected is not None and secrets.compare_digest(expected, code)
