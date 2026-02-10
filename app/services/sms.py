import random
import string
from abc import ABC, abstractmethod

from app.config import settings


class SMSProvider(ABC):
    @abstractmethod
    async def send_sms(self, phone: str, message: str) -> bool:
        pass


class MockSMSProvider(SMSProvider):
    """Mock SMS provider for development/testing"""

    async def send_sms(self, phone: str, message: str) -> bool:
        print(f"[MOCK SMS] To: {phone}, Message: {message}")
        return True


class TwilioProvider(SMSProvider):
    """Twilio SMS provider - implement when ready"""

    async def send_sms(self, phone: str, message: str) -> bool:
        # TODO: Implement Twilio integration
        # from twilio.rest import Client
        # client = Client(settings.SMS_API_KEY, settings.SMS_API_SECRET)
        # message = client.messages.create(
        #     body=message,
        #     from_=settings.SMS_SENDER_NUMBER,
        #     to=phone
        # )
        raise NotImplementedError("Twilio provider not implemented")


class NHNCloudProvider(SMSProvider):
    """NHN Cloud SMS provider - implement when ready"""

    async def send_sms(self, phone: str, message: str) -> bool:
        # TODO: Implement NHN Cloud integration
        raise NotImplementedError("NHN Cloud provider not implemented")


class SMSService:
    def __init__(self, provider: SMSProvider | None = None):
        self.provider = provider or MockSMSProvider()

    def generate_verification_code(self, length: int = 6) -> str:
        return "".join(random.choices(string.digits, k=length))

    async def send_verification_code(self, phone: str, code: str) -> bool:
        message = f"[TLM] 인증번호: {code}"
        return await self.provider.send_sms(phone, message)


def get_sms_service() -> SMSService:
    # Switch provider based on configuration
    if settings.SMS_API_KEY:
        # Return appropriate provider when configured
        pass
    return SMSService(MockSMSProvider())
