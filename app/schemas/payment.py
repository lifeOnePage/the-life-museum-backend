from pydantic import BaseModel, model_validator


class PaymentConfirmRequest(BaseModel):
    stripe_session_id: str | None = None
    imp_uid: str | None = None
    merchant_uid: str | None = None

    @model_validator(mode="after")
    def require_at_least_one(self):
        if not self.stripe_session_id and not self.imp_uid:
            raise ValueError(
                "Either stripe_session_id or imp_uid must be provided"
            )
        return self


class PaymentConfirmResponse(BaseModel):
    ok: bool
    message: str
