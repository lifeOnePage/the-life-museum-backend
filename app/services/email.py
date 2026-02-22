import random
import string


class MockEmailProvider:
    """Mock email provider for development/testing"""

    async def send_email(self, email: str, message: str) -> bool:
        print(f"[MOCK EMAIL] To: {email}, Message: {message}")
        return True


class EmailService:
    def __init__(self, provider: MockEmailProvider | None = None):
        self.provider = provider or MockEmailProvider()

    def generate_verification_code(self, length: int = 6) -> str:
        return "".join(random.choices(string.digits, k=length))

    async def send_verification_code(self, email: str, code: str) -> bool:
        message = f"[TLM] 이메일 인증번호: {code}"
        return await self.provider.send_email(email, message)


def get_email_service() -> EmailService:
    return EmailService(MockEmailProvider())
