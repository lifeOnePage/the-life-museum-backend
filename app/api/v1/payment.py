from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.payment import PaymentConfirmRequest, PaymentConfirmResponse
from app.services.payment import PaymentService, PaymentVerificationError

router = APIRouter()


@router.post("/confirm", response_model=PaymentConfirmResponse)
async def confirm_payment(
    body: PaymentConfirmRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """결제 게이트웨이 검증. Stripe 또는 PortOne 결제를 확인하고 감사 레코드 저장."""
    service = PaymentService(db)

    try:
        if body.stripe_session_id:
            await service.verify_stripe(user.id, body.stripe_session_id)
        elif body.imp_uid:
            await service.verify_portone(user.id, body.imp_uid, body.merchant_uid)
    except PaymentVerificationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await db.commit()
    return {"ok": True, "message": "Payment confirmed"}
