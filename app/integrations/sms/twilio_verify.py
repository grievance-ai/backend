"""Twilio Verify provider — Twilio issues and checks the code itself.

Ported from nebryx's twilioVerifyService.js: ``send_code`` starts a verification
on the configured Verify service, and ``check_code`` approves it. The locally
stored code is unused (there is none), so ``manages_codes`` is True.
"""

from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.integrations.sms.base import SMSProvider

logger = get_logger(__name__)


class TwilioVerifyProvider(SMSProvider):
    manages_codes = True

    def _service(self) -> Any:
        from twilio.rest import Client

        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        return client.verify.v2.services(settings.twilio_service_sid)

    def send_code(self, *, number: str, code: str | None) -> None:
        self._service().verifications.create(to=number, channel="sms")

    def check_code(self, *, number: str, code: str, expected: str | None) -> bool:
        try:
            check = self._service().verification_checks.create(to=number, code=code)
        except Exception:
            logger.warning("twilio_verify_check_failed", exc_info=True)
            return False
        return bool(check.status == "approved")
