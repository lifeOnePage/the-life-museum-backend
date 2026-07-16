import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CouponRedeemRequest(BaseModel):
    code: str = Field(min_length=1, max_length=50)


class CouponAdminAuthRequest(BaseModel):
    password: str = Field(min_length=1)


class CouponGenerateRequest(BaseModel):
    credit_amount: int = Field(gt=0, le=1_000_000)
    count: int = Field(default=1, ge=1, le=100)
    prefix: str = Field(default="TLM", min_length=1, max_length=10)


class CouponResponse(BaseModel):
    id: uuid.UUID
    code: str
    credit_amount: int
    is_used: bool
    used_at: datetime | None
    used_by_email: str | None = None
    created_at: datetime
