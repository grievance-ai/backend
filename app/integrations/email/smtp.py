"""SMTP email provider (stdlib ``smtplib``).

Synchronous on purpose: it runs inside the Celery worker, which has no event
loop. Sends a multipart/alternative message (plain text + HTML).
"""

import smtplib
from email.message import EmailMessage as MIMEMessage
from email.utils import formataddr

from app.core.config import settings
from app.integrations.email.base import EmailMessage


class SMTPEmailProvider:
    def send(self, message: EmailMessage) -> None:
        mime = MIMEMessage()
        mime["From"] = formataddr((message.from_name, message.from_email))
        mime["To"] = message.to
        mime["Subject"] = message.subject
        mime.set_content(message.text)
        mime.add_alternative(message.html, subtype="html")

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as client:
            if settings.smtp_use_tls:
                client.starttls()
            if settings.smtp_username:
                client.login(settings.smtp_username, settings.smtp_password)
            client.send_message(mime)
