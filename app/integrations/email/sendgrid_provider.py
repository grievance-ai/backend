"""SendGrid email provider (synchronous SDK).

Raises on any non-2xx response so the Celery task retries.
"""

from app.core.config import settings
from app.integrations.email.base import EmailMessage


class SendGridEmailProvider:
    def send(self, message: EmailMessage) -> None:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Content, Email, Mail, To

        mail = Mail(
            from_email=Email(message.from_email, message.from_name),
            to_emails=To(message.to),
            subject=message.subject,
            plain_text_content=Content("text/plain", message.text),
            html_content=Content("text/html", message.html),
        )
        response = SendGridAPIClient(settings.sendgrid_api_key).send(mail)
        if response.status_code >= 300:
            raise RuntimeError(f"sendgrid rejected the message: HTTP {response.status_code}")
