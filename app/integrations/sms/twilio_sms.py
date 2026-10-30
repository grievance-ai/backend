"""Twilio Programmable SMS provider (self-managed code, synchronous SDK)."""

from app.core.config import settings
from app.integrations.sms.base import SMSProvider, verification_body


class TwilioSMSProvider(SMSProvider):
    def send_code(self, *, number: str, code: str | None) -> None:
        if code is None:
            return
        from twilio.rest import Client

        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        client.messages.create(
            to=number,
            from_=settings.twilio_from_number,
            body=verification_body(code),
        )
