import random
import string
import logging
from abc import ABC, abstractmethod
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

from app.config import settings

logger = logging.getLogger(__name__)

_VERIFICATION_HTML = """\
<div style="font-family:sans-serif;max-width:480px;margin:0 auto;padding:24px;">
  <h2>The Life Museum</h2>
  <p style="color:#555;">이메일 인증번호입니다.</p>
  <div style="font-size:36px;font-weight:bold;letter-spacing:10px;padding:20px 0;">{code}</div>
  <p style="color:#888;font-size:12px;">5분 이내에 입력해 주세요. 본인이 요청하지 않은 경우 무시하세요.</p>
</div>"""


class EmailProvider(ABC):
    @abstractmethod
    async def send_email(self, to: str, subject: str, html: str) -> bool: ...


class MockEmailProvider(EmailProvider):
    """Mock email provider for development/testing"""

    async def send_email(self, to: str, subject: str, html: str) -> bool:
        print(f"[MOCK EMAIL] To: {to}, Subject: {subject}\n{html}")
        return True


class GmailSMTPProvider(EmailProvider):
    SMTP_HOST = "smtp.gmail.com"
    SMTP_PORT = 587

    def __init__(self, user: str, app_password: str):
        self.user = user
        self.app_password = app_password
        self.sender = f"The Life Museum <{user}>"

    async def send_email(self, to: str, subject: str, html: str) -> bool:
        message = MIMEMultipart("alternative")
        message["From"] = self.sender
        message["To"] = to
        message["Subject"] = subject
        message.attach(MIMEText(html, "html"))

        try:
            await aiosmtplib.send(
                message,
                hostname=self.SMTP_HOST,
                port=self.SMTP_PORT,
                username=self.user,
                password=self.app_password,
                start_tls=True,
            )
            logger.info("Gmail SMTP sent to %s", to)
            return True
        except Exception as e:
            logger.error("Gmail SMTP error: %s", e)
            return False


class EmailService:
    def __init__(self, provider: EmailProvider | None = None):
        self.provider = provider or MockEmailProvider()

    def generate_verification_code(self, length: int = 6) -> str:
        return "".join(random.choices(string.digits, k=length))

    async def send_verification_code(self, email: str, code: str) -> bool:
        subject = "[The Life Museum] 이메일 인증번호"
        html = _VERIFICATION_HTML.format(code=code)
        return await self.provider.send_email(email, subject, html)


def get_email_service() -> EmailService:
    if settings.GMAIL_USER and settings.GMAIL_APP_PASSWORD:
        return EmailService(GmailSMTPProvider(settings.GMAIL_USER, settings.GMAIL_APP_PASSWORD))
    return EmailService(MockEmailProvider())
