from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.services.credit import (
    CreditService,
    InsufficientCreditsError,
    PACKAGES,
)
from app.schemas.credit import (
    CreditPurchaseRequest,
    CreditDeductRequest,
    CreditTransactionResponse,
)

router = APIRouter()


@router.get("/balance")
async def get_balance(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = CreditService(db)
    balance = await service.get_balance(user.id)
    return {"credits": balance}


@router.post("/purchase")
async def purchase_credits(
    body: CreditPurchaseRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """크레딧 패키지 구매. 현재는 결제 성공 가정 -> 즉시 충전."""
    if body.package not in PACKAGES:
        raise HTTPException(400, "Invalid package")

    service = CreditService(db)
    tx = await service.add_credits(user.id, body.package, reference_id=None)
    await db.commit()
    return {"credits": tx.balance_after, "added": tx.amount}


@router.post("/deduct")
async def deduct_credits(
    body: CreditDeductRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """크레딧 차감. 앨범 생성/이모지 구매 시 호출."""
    tx_type = body.tx_type
    if body.tx_type == "emoji_buy":
        tx_type = f"emoji_{body.emoji_type or 'regular'}"

    try:
        service = CreditService(db)
        tx = await service.deduct_credits(
            user.id, tx_type, reference_id=body.reference_id
        )
        await db.commit()
        return {"credits": tx.balance_after, "deducted": abs(tx.amount)}
    except InsufficientCreditsError as e:
        raise HTTPException(402, str(e))


@router.get("/history")
async def get_history(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = CreditService(db)
    txs = await service.get_history(user.id)
    return [CreditTransactionResponse.model_validate(tx) for tx in txs]
