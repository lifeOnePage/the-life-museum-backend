from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.services.credit import (
    CreditService,
    InsufficientCreditsError,
    PACKAGES,
)
from app.services.payment import PaymentService, PaymentVerificationError
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
    """크레딧 패키지 구매. PortOne V2 결제 검증 통과 시에만 충전 (멱등)."""
    if body.package not in PACKAGES:
        raise HTTPException(400, "Invalid package")
    if not body.payment_id:
        raise HTTPException(400, "payment_id is required")

    payment_service = PaymentService(db)

    # 멱등성: 이미 처리된 결제면 재충전하지 않고 현재 잔액 반환
    existing = await payment_service._find_by_tx_id(body.payment_id)
    if existing:
        balance = await CreditService(db).get_balance(user.id)
        return {"credits": balance, "added": 0, "already": True}

    # PortOne V2 결제 검증 (status=PAID + 금액 일치)
    try:
        await payment_service.verify_portone_v2(
            user.id, body.payment_id, body.package
        )
    except PaymentVerificationError as e:
        await db.rollback()
        raise HTTPException(400, str(e))

    # 검증 통과 → 크레딧 충전 (Payment insert와 동일 트랜잭션)
    tx = await CreditService(db).add_credits(
        user.id, body.package, reference_id=body.payment_id
    )

    try:
        await db.commit()
    except IntegrityError:
        # 동시 요청으로 같은 payment_id가 이미 커밋됨 → 중복 충전 방지
        await db.rollback()
        balance = await CreditService(db).get_balance(user.id)
        return {"credits": balance, "added": 0, "already": True}

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
