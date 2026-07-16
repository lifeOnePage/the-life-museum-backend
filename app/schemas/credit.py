import uuid
from datetime import datetime

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class CreditPurchaseRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    package: str  # "credit_1000" | "credit_3000" | "credit_6000"
    # PortOne V2 결제 ID — 서버측 검증에 사용 (camelCase paymentId 도 허용)
    payment_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("payment_id", "paymentId"),
    )
    coupon_code: str | None = Field(
        default=None,
        validation_alias=AliasChoices("coupon_code", "couponCode"),
    )


class CreditDeductRequest(BaseModel):
    tx_type: str  # "album_create" | "emoji_buy"
    reference_id: str | None = None
    emoji_type: str | None = None  # "regular" | "limited"


class CreditBalanceResponse(BaseModel):
    credits: int


class CreditTransactionResponse(BaseModel):
    id: uuid.UUID
    tx_type: str
    amount: int
    balance_after: int
    description: str | None
    reference_id: str | None
    created_at: datetime

    class Config:
        from_attributes = True
