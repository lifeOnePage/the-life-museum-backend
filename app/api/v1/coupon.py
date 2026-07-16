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
)

router = APIRouter()

# ── 유저: 쿠폰 등록 ─────────────────────────────────────────


@router.post("/redeem")
async def redeem_coupon(
    body: CouponRedeemRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """쿠폰 코드 등록 → 크레딧 지급. 쿠폰 행 잠금으로 중복 사용 방지."""
    code = body.code.strip().upper()

    result = await db.execute(
        select(Coupon).where(Coupon.code == code).with_for_update()
    )
    coupon = result.scalar_one_or_none()
    if coupon is None:
        raise HTTPException(404, "존재하지 않는 쿠폰 코드입니다.")
    if coupon.is_used:
        raise HTTPException(409, "이미 사용된 쿠폰입니다.")

    result = await db.execute(
        select(User).where(User.id == user.id).with_for_update()
    )
    locked_user = result.scalar_one()

    new_balance = locked_user.credits + coupon.credit_amount
    locked_user.credits = new_balance

    coupon.is_used = True
    coupon.used_at = datetime.now(timezone.utc)
    coupon.used_by_user_id = user.id

    tx = CreditTransaction(
        user_id=user.id,
        tx_type=TxType.ADMIN,
        amount=coupon.credit_amount,
        balance_after=new_balance,
        description=f"쿠폰 등록 ({code})",
        reference_id=f"coupon:{coupon.id}",
    )
    db.add(tx)
    await db.commit()

    return {"credits": new_balance, "added": coupon.credit_amount}


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
        Coupon(code=code, credit_amount=body.credit_amount)
        for code in sorted(codes)
    ]
    db.add_all(coupons)
    await db.commit()

    return {
        "coupons": [
            {"code": c.code, "credit_amount": c.credit_amount} for c in coupons
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

    result = await db.execute(
        select(Coupon, User.email)
        .outerjoin(User, Coupon.used_by_user_id == User.id)
        .order_by(Coupon.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    items = [
        CouponResponse(
            id=coupon.id,
            code=coupon.code,
            credit_amount=coupon.credit_amount,
            is_used=coupon.is_used,
            used_at=coupon.used_at,
            used_by_email=email,
            created_at=coupon.created_at,
        )
        for coupon, email in result.all()
    ]
    return {"total": total, "used": used, "items": items}
