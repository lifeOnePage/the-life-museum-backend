import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CouponRedeemRequest(BaseModel):
    code: str = Field(min_length=1, max_length=50)


class CouponAdminAuthRequest(BaseModel):
    password: str = Field(min_length=1)


class CouponGenerateRequest(BaseModel):
    coupon_type: str = Field(default="credit", pattern="^(credit|discount)$")
    # credit 타입 전용
    credit_amount: int | None = Field(default=None, gt=0, le=1_000_000)
    # discount 타입 전용
    discount_percent: int | None = Field(default=None, ge=1, le=100)
    max_discount_krw: int | None = Field(default=None, gt=0, le=10_000_000)
    count: int = Field(default=1, ge=1, le=100)
    prefix: str = Field(default="TLM", min_length=1, max_length=10)


class CouponResponse(BaseModel):
    id: uuid.UUID
    code: str
    coupon_type: str
    credit_amount: int | None
    discount_percent: int | None
    max_discount_krw: int | None
    is_used: bool
    used_at: datetime | None
    used_by_email: str | None = None
    claimed_by_email: str | None = None
    created_at: datetime


class MyCouponResponse(BaseModel):
    code: str
    discount_percent: int
    max_discount_krw: int
    claimed_at: datetime | None
