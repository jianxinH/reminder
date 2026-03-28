import smtplib
from email.message import EmailMessage

from app.core.config import get_settings


class EmailService:
    def __init__(self):
        self.settings = get_settings()

    @property
    def is_configured(self) -> bool:
        return bool(
            self.settings.smtp_host
            and self.settings.smtp_port
            and self.settings.smtp_username
            and self.settings.smtp_password
            and self.settings.smtp_from_email
        )

    def send_message(self, to_email: str, subject: str, text: str) -> dict:
        if not self.is_configured:
            return {"ok": False, "description": "SMTP is not configured"}

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.settings.smtp_from_email
        msg["To"] = to_email
        msg.set_content(text)

        with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=10) as server:
            if self.settings.smtp_use_tls:
                server.starttls()
            server.login(self.settings.smtp_username, self.settings.smtp_password)
            server.send_message(msg)

        return {"ok": True}
