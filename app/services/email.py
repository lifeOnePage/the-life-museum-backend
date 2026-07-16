import base64
import random
import string
import logging
import time
from abc import ABC, abstractmethod
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_VERIFICATION_HTML = """\
<div style="font-family:sans-serif;max-width:480px;margin:0 auto;padding:24px;">
  <h2>theLIFEmemory</h2>
  <p style="color:#555;">이메일 인증번호입니다.</p>
  <div style="font-size:36px;font-weight:bold;letter-spacing:10px;padding:20px 0;">{code}</div>
  <p style="color:#888;font-size:12px;">5분 이내에 입력해 주세요. 본인이 요청하지 않은 경우 무시하세요.</p>
</div>"""

_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


class EmailProvider(ABC):
    @abstractmethod
    async def send_email(self, to: str, subject: str, html: str) -> bool: ...


class MockEmailProvider(EmailProvider):
    """Mock email provider for development/testing"""

    async def send_email(self, to: str, subject: str, html: str) -> bool:
        print(f"[MOCK EMAIL] To: {to}, Subject: {subject}\n{html}")
        return True


class GmailAPIProvider(EmailProvider):
    """Gmail API provider using OAuth2 refresh token (HTTPS — works on Railway)."""

    def __init__(self, user: str, refresh_token: str, client_id: str, client_secret: str):
        self.user = user
        self.refresh_token = refresh_token
        self.client_id = client_id
        self.client_secret = client_secret
        self.sender = f"theLIFEmemory <{user}>"
        self._cached_token: str | None = None
        self._token_expires_at: float = 0

    async def _get_access_token(self, client: httpx.AsyncClient) -> str:
        if self._cached_token and time.time() < self._token_expires_at - 60:
            return self._cached_token

        t0 = time.time()
        resp = await client.post(
            _GOOGLE_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        self._cached_token = data["access_token"]
        self._token_expires_at = time.time() + data.get("expires_in", 3600)
        logger.info("Gmail OAuth token refreshed in %.1fs", time.time() - t0)
        return self._cached_token

    async def send_email(self, to: str, subject: str, html: str) -> bool:
        message = MIMEMultipart("alternative")
        message["From"] = self.sender
        message["To"] = to
        message["Subject"] = subject
        message.attach(MIMEText(html, "html"))

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

        try:
            async with httpx.AsyncClient() as client:
                t0 = time.time()
                access_token = await self._get_access_token(client)
                resp = await client.post(
                    _GMAIL_SEND_URL,
                    headers={"Authorization": f"Bearer {access_token}"},
                    json={"raw": raw},
                    timeout=10.0,
                )
                resp.raise_for_status()
                logger.info("Gmail API sent to %s in %.1fs", to, time.time() - t0)
                return True
        except Exception as e:
            logger.error("Gmail API error: %s", e)
            return False


class EmailService:
    def __init__(self, provider: EmailProvider | None = None):
        self.provider = provider or MockEmailProvider()

    def generate_verification_code(self, length: int = 6) -> str:
        return "".join(random.choices(string.digits, k=length))

    async def send_verification_code(self, email: str, code: str) -> bool:
        subject = "[theLIFEmemory] 이메일 인증번호"
        html = _VERIFICATION_HTML.format(code=code)
        return await self.provider.send_email(email, subject, html)


_email_service: EmailService | None = None


def get_email_service() -> EmailService:
    global _email_service
    if _email_service is not None:
        return _email_service

    if (
        settings.GMAIL_USER
        and settings.GMAIL_REFRESH_TOKEN
        and settings.GOOGLE_CLIENT_ID
        and settings.GOOGLE_CLIENT_SECRET
    ):
        _email_service = EmailService(
            GmailAPIProvider(
                user=settings.GMAIL_USER,
                refresh_token=settings.GMAIL_REFRESH_TOKEN,
                client_id=settings.GOOGLE_CLIENT_ID,
                client_secret=settings.GOOGLE_CLIENT_SECRET,
            )
        )
    else:
        _email_service = EmailService(MockEmailProvider())
    return _email_service
