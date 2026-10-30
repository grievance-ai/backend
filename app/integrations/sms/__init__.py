"""SMS provider selection — ported from nebryx's smsService.initializeProvider.

``get_provider()`` returns the provider named by ``SMS_PROVIDER``: ``mock``
(default, offline), ``twilio_sms`` / ``aws_sns`` (we generate and verify the
code), or ``twilio_verify`` (Twilio issues and checks the code).
"""

from app.core.config import settings
from app.integrations.sms.aws_sns import AWSSNSProvider
from app.integrations.sms.base import SMSMessage, SMSProvider
from app.integrations.sms.mock import MockSMSProvider
from app.integrations.sms.twilio_sms import TwilioSMSProvider
from app.integrations.sms.twilio_verify import TwilioVerifyProvider

__all__ = ["SMSMessage", "SMSProvider", "get_provider"]


def get_provider() -> SMSProvider:
    provider = settings.sms_provider.lower()
    if provider == "twilio_sms":
        return TwilioSMSProvider()
    if provider == "twilio_verify":
        return TwilioVerifyProvider()
    if provider == "aws_sns":
        return AWSSNSProvider()
    return MockSMSProvider()
