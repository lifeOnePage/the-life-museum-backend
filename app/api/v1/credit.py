from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.deps import get_current_user
from app.models.coupon import Coupon
from app.models.user import User
from app.services.coupon import discounted_prices
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
    """크레딧 패키지 구매. PortOne V2 결제 검증 통과 시에만 충전 (멱등).

    coupon_code가 오면 보관함의 할인 쿠폰을 검증해 할인가로 금액을 대조하고,
    충전 성공 시 쿠폰을 소모 처리한다 (전 과정 동일 트랜잭션).
    """
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

    # ── 할인 쿠폰 검증 (행 잠금 — 동시 사용 방지) ──
    pkg = PACKAGES[body.package]
    coupon = None
    expected_krw = None
    expected_usd = None
    if body.coupon_code:
        code = body.coupon_code.strip().upper()
        result = await db.execute(
            select(Coupon).where(Coupon.code == code).with_for_update()
        )
        coupon = result.scalar_one_or_none()
        if (
            coupon is None
            or coupon.coupon_type != "discount"
            or coupon.claimed_by_user_id != user.id
        ):
            raise HTTPException(400, "사용할 수 없는 쿠폰입니다.")
        if coupon.is_used:
            raise HTTPException(409, "이미 사용된 쿠폰입니다.")
        expected_krw, expected_usd = discounted_prices(
            pkg["price_krw"],
            pkg["price_usd"],
            coupon.discount_percent or 0,
            coupon.max_discount_krw or 0,
        )

    # PortOne V2 결제 검증 (status=PAID + 금액 일치 — 쿠폰 적용 시 할인가 기준)
    try:
        await payment_service.verify_portone_v2(
            user.id,
            body.payment_id,
            body.package,
            expected_krw=expected_krw,
            expected_usd=expected_usd,
        )
    except PaymentVerificationError as e:
        await db.rollback()
        raise HTTPException(400, str(e))

    # 검증 통과 → 크레딧 충전 (Payment insert와 동일 트랜잭션)
    tx = await CreditService(db).add_credits(
        user.id, body.package, reference_id=body.payment_id
    )

    # 쿠폰 소모 (충전과 동일 트랜잭션 — 커밋 실패 시 함께 롤백)
    if coupon is not None:
        coupon.is_used = True
        coupon.used_at = datetime.now(timezone.utc)
        coupon.used_by_user_id = user.id

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
