import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import settings
from app.core.security import decode_token
from app.database import get_db
from app.models.coupon import Coupon
from app.models.credit import CreditTransaction, TxType
from app.models.user import User
from app.schemas.coupon import (
    CouponAdminAuthRequest,
    CouponGenerateRequest,
    CouponRedeemRequest,
    CouponResponse,
    MyCouponResponse,
)

router = APIRouter()

# ── 유저: 쿠폰 등록 ─────────────────────────────────────────


@router.post("/redeem")
async def redeem_coupon(
    body: CouponRedeemRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """쿠폰 코드 등록. 쿠폰 행 잠금으로 중복 사용 방지.

    - credit 타입: 즉시 크레딧 지급 후 소모
    - album 타입: 즉시 앨범 생성권(credits) 지급 후 소모 — 지급 경로는 credit과 동일
    - discount 타입: 유저 보관함에 등록(claim) — 실제 소모는 충전 결제에서
    """
    code = body.code.strip().upper()

    result = await db.execute(
        select(Coupon).where(Coupon.code == code).with_for_update()
    )
    coupon = result.scalar_one_or_none()
    if coupon is None:
        raise HTTPException(404, "존재하지 않는 쿠폰 코드입니다.")
    if coupon.is_used:
        raise HTTPException(409, "이미 사용된 쿠폰입니다.")

    # ── 할인 쿠폰: 보관함 등록 ──
    if coupon.coupon_type == "discount":
        if coupon.claimed_by_user_id is not None:
            if coupon.claimed_by_user_id == user.id:
                raise HTTPException(409, "이미 보관함에 등록된 쿠폰입니다.")
            raise HTTPException(409, "이미 다른 계정에 등록된 쿠폰입니다.")
        coupon.claimed_by_user_id = user.id
        coupon.claimed_at = datetime.now(timezone.utc)
        await db.commit()
        return {
            "type": "discount",
            "coupon": {
                "code": coupon.code,
                "discountPercent": coupon.discount_percent,
                "maxDiscountKrw": coupon.max_discount_krw,
            },
        }

    # ── 크레딧/앨범 생성권 쿠폰: 즉시 지급 ──
    # 앨범 생성권 = users.credits 자체이므로 두 타입 모두 동일 경로로 지급
    result = await db.execute(
        select(User).where(User.id == user.id).with_for_update()
    )
    locked_user = result.scalar_one()

    new_balance = locked_user.credits + (coupon.credit_amount or 0)
    locked_user.credits = new_balance

    coupon.is_used = True
    coupon.used_at = datetime.now(timezone.utc)
    coupon.used_by_user_id = user.id

    tx = CreditTransaction(
        user_id=user.id,
        tx_type=TxType.ADMIN,
        amount=coupon.credit_amount or 0,
        balance_after=new_balance,
        description=f"쿠폰 등록 ({code})",
        reference_id=f"coupon:{coupon.id}",
    )
    db.add(tx)
    await db.commit()

    return {
        "type": coupon.coupon_type,  # "credit" | "album"
        "credits": new_balance,
        "added": coupon.credit_amount or 0,
    }


@router.get("/my")
async def my_coupons(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """내 보관함의 미사용 할인 쿠폰 목록 (충전 탭 리스트용)."""
    result = await db.execute(
        select(Coupon)
        .where(
            Coupon.claimed_by_user_id == user.id,
            Coupon.coupon_type == "discount",
            Coupon.is_used.is_(False),
        )
        .order_by(Coupon.claimed_at.desc())
    )
    coupons = result.scalars().all()
    return {
        "items": [
            MyCouponResponse(
                code=c.code,
                discount_percent=c.discount_percent or 0,
                max_discount_krw=c.max_discount_krw or 0,
                claimed_at=c.claimed_at,
            )
            for c in coupons
        ]
    }


# ── 관리자 인증 (패스워드 → 단기 토큰) ──────────────────────

COUPON_ADMIN_TOKEN_TYPE = "coupon_admin"
COUPON_ADMIN_TOKEN_TTL = timedelta(hours=2)

_admin_bearer = HTTPBearer(auto_error=False)


def _create_admin_token() -> str:
    expire = datetime.now(timezone.utc) + COUPON_ADMIN_TOKEN_TTL
    return jwt.encode(
        {"exp": expire, "type": COUPON_ADMIN_TOKEN_TYPE},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )


async def require_coupon_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(_admin_bearer),
) -> None:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="관리자 인증이 필요합니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(credentials.credentials)
    if payload is None or payload.get("type") != COUPON_ADMIN_TOKEN_TYPE:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않거나 만료된 관리자 토큰입니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.post("/admin/auth")
async def coupon_admin_auth(body: CouponAdminAuthRequest):
    """발행 페이지 패스워드 검증 → 2시간짜리 관리자 토큰 발급."""
    if not settings.COUPON_ADMIN_PASSWORD:
        raise HTTPException(503, "쿠폰 관리자 비밀번호가 설정되지 않았습니다.")
    if not secrets.compare_digest(
        body.password.encode(), settings.COUPON_ADMIN_PASSWORD.encode()
    ):
        raise HTTPException(401, "비밀번호가 올바르지 않습니다.")
    return {
        "token": _create_admin_token(),
        "expires_in": int(COUPON_ADMIN_TOKEN_TTL.total_seconds()),
    }


# ── 관리자: 쿠폰 발행 / 목록 ────────────────────────────────

# 혼동되는 문자(I, O, 0, 1) 제외
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _random_code(prefix: str) -> str:
    part = lambda: "".join(secrets.choice(_CODE_ALPHABET) for _ in range(4))
    return f"{prefix}-{part()}-{part()}"


@router.post(
    "/admin/generate",
    dependencies=[Depends(require_coupon_admin)],
)
async def generate_coupons(
    body: CouponGenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    prefix = body.prefix.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{1,10}", prefix):
        raise HTTPException(400, "prefix는 영문/숫자 1~10자만 가능합니다.")

    # 타입별 필수값 검증
    # credit_amount: credit 타입은 크레딧, album 타입은 앨범 생성권 개수로 재사용
    if body.coupon_type == "credit":
        if not body.credit_amount:
            raise HTTPException(400, "크레딧 쿠폰은 credit_amount가 필요합니다.")
        credit_amount = body.credit_amount
    elif body.coupon_type == "album":
        credit_amount = body.credit_amount or 1  # 미지정 시 앨범 생성권 1개
        if credit_amount > 100:
            raise HTTPException(400, "앨범 생성권 쿠폰은 100개 이하만 가능합니다.")
    else:  # discount
        if not body.discount_percent or not body.max_discount_krw:
            raise HTTPException(
                400, "할인 쿠폰은 discount_percent와 max_discount_krw가 필요합니다."
            )
        credit_amount = None

    # 배치 내 중복 + DB 기존 코드와 충돌 방지
    codes: set[str] = set()
    while len(codes) < body.count:
        codes.add(_random_code(prefix))

    result = await db.execute(select(Coupon.code).where(Coupon.code.in_(codes)))
    existing = set(result.scalars().all())
    while existing & codes:
        codes -= existing
        while len(codes) < body.count:
            codes.add(_random_code(prefix))
        result = await db.execute(
            select(Coupon.code).where(Coupon.code.in_(codes))
        )
        existing = set(result.scalars().all())

    coupons = [
        Coupon(
            code=code,
            coupon_type=body.coupon_type,
            credit_amount=credit_amount,
            discount_percent=(
                body.discount_percent if body.coupon_type == "discount" else None
            ),
            max_discount_krw=(
                body.max_discount_krw if body.coupon_type == "discount" else None
            ),
        )
        for code in sorted(codes)
    ]
    db.add_all(coupons)
    await db.commit()

    return {
        "coupons": [
            {
                "code": c.code,
                "coupon_type": c.coupon_type,
                "credit_amount": c.credit_amount,
                "discount_percent": c.discount_percent,
                "max_discount_krw": c.max_discount_krw,
            }
            for c in coupons
        ]
    }


@router.get(
    "/admin/list",
    dependencies=[Depends(require_coupon_admin)],
)
async def list_coupons(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    total = (await db.execute(select(func.count(Coupon.id)))).scalar_one()
    used = (
        await db.execute(
            select(func.count(Coupon.id)).where(Coupon.is_used.is_(True))
        )
    ).scalar_one()

    from sqlalchemy.orm import aliased

    UsedBy = aliased(User)
    ClaimedBy = aliased(User)
    result = await db.execute(
        select(Coupon, UsedBy.email, ClaimedBy.email)
        .outerjoin(UsedBy, Coupon.used_by_user_id == UsedBy.id)
        .outerjoin(ClaimedBy, Coupon.claimed_by_user_id == ClaimedBy.id)
        .order_by(Coupon.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    items = [
        CouponResponse(
            id=coupon.id,
            code=coupon.code,
            coupon_type=coupon.coupon_type,
            credit_amount=coupon.credit_amount,
            discount_percent=coupon.discount_percent,
            max_discount_krw=coupon.max_discount_krw,
            is_used=coupon.is_used,
            used_at=coupon.used_at,
            used_by_email=used_email,
            claimed_by_email=claimed_email,
            created_at=coupon.created_at,
        )
        for coupon, used_email, claimed_email in result.all()
    ]
    return {"total": total, "used": used, "items": items}
