"""AWS SNS SMS provider (self-managed code, synchronous boto3 client).

Credentials are resolved from the standard AWS chain; only the region is set.
"""

from app.core.config import settings
from app.integrations.sms.base import SMSProvider, verification_body


class AWSSNSProvider(SMSProvider):
    def send_code(self, *, number: str, code: str | None) -> None:
        if code is None:
            return
        import boto3

        client = boto3.client("sns", region_name=settings.aws_region)
        client.publish(PhoneNumber=number, Message=verification_body(code))
