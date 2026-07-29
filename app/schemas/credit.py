from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class CreditPurchaseRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    package: str  # "album_1" | "album_3" | "album_6"
    # PortOne V2 결제 ID — 서버측 검증에 사용 (camelCase paymentId 도 허용)
    payment_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("payment_id", "paymentId"),
    )
    coupon_code: str | None = Field(
        default=None,
        validation_alias=AliasChoices("coupon_code", "couponCode"),
    )


class CreditBalanceResponse(BaseModel):
    credits: int
