import uuid
from datetime import datetime

from pydantic import BaseModel


class CreditPurchaseRequest(BaseModel):
    package: str  # "credit_1000" | "credit_3900" | "credit_9900"


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
