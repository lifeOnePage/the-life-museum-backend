import random
import string
import logging
from abc import ABC, abstractmethod

import httpx

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


class ResendEmailProvider(EmailProvider):
    def __init__(self, api_key: str, sender: str):
        self.api_key = api_key
        self.sender = sender

    async def send_email(self, to: str, subject: str, html: str) -> bool:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.resend.com/emails",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={"from": self.sender, "to": [to], "subject": subject, "html": html},
                    timeout=10.0,
                )
                return response.status_code == 200
        except Exception as e:
            logger.error("Resend email error: %s", e)
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
    if settings.RESEND_API_KEY:
        return EmailService(ResendEmailProvider(settings.RESEND_API_KEY, settings.EMAIL_FROM))
    return EmailService(MockEmailProvider())
