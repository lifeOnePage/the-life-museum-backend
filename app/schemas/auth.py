from pydantic import BaseModel, EmailStr


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    sub: str
    exp: int
    type: str


class LoginRequest(BaseModel):
    email: EmailStr | None = None
    phone: str | None = None
    password: str


class PhoneVerificationRequest(BaseModel):
    phone: str


class PhoneVerificationConfirm(BaseModel):
    phone: str
    code: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str
