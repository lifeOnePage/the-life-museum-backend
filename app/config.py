from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # App
    APP_NAME: str = "TLM Backend"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/tlm"

    # JWT
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # OAuth - Google
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/google/callback"

    # OAuth - Kakao
    KAKAO_CLIENT_ID: str = ""
    KAKAO_CLIENT_SECRET: str = ""
    KAKAO_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/kakao/callback"

    # Email (Gmail API)
    GMAIL_USER: str = ""
    GMAIL_REFRESH_TOKEN: str = ""

    # SMS (placeholder - configure when service is selected)
    SMS_API_KEY: str = ""
    SMS_API_SECRET: str = ""
    SMS_SENDER_NUMBER: str = ""

    # OpenAI
    OPENAI_API_KEY: str = ""

    # Mindlogic API Gateway
    GATEWAY_API_KEY: str = ""
    GATEWAY_BASE_URL: str = "https://factchat-cloud.mindlogic.ai/v1/gateway"

    # Google Gemini
    GOOGLE_GEMINI_API_KEY: str = ""

    # Replicate
    REPLICATE_API_TOKEN: str = ""

    # Stability AI
    STABILITY_API_KEY: str = ""

    # Cloudflare R2
    R2_ACCOUNT_ID: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET_NAME: str = ""
    R2_PUBLIC_URL: str = ""

    # Payment Gateways
    STRIPE_SECRET_KEY: str = ""
    PORTONE_API_KEY: str = ""
    PORTONE_API_SECRET: str = ""

    # Admin
    ADMIN_EMAILS: str = "goodchaeee@naver.com,goodchaeee@gmail.com,akea1027th@gmail.com,byul88byul@gmail.com,jusub@sogang.ac.kr,showyourmind@gmail.com"

    # Dev
    DEV_AUTH_KEY: str = ""

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
