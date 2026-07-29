from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.credit import CreditTransaction, TxType
from app.config import settings

ADMIN_EMAILS = {e.strip() for e in settings.ADMIN_EMAILS.split(",") if e.strip()}

# 앨범 결제 상품 — "포인트/크레딧 충전"이 아니라 "앨범 생성권 N개"를 직접 구매하는
# 구조 (KG이니시스 심사 대응: 범용 선불 포인트가 아닌 특정 디지털 상품 판매).
# price_usd는 PayPal 재도입 시를 대비해 남겨두되, 현재는 KRW 결제만 사용한다.
PACKAGES = {
    "album_1": {"albums": 1, "price_krw": 9000, "price_usd": 699},
    "album_3": {"albums": 3, "price_krw": 24000, "price_usd": 1899},
    "album_6": {"albums": 6, "price_krw": 39000, "price_usd": 2999},
    # 임시 결제 테스트용 — 실 서비스 오픈 전 제거할 것 (PG 최소 결제금액 1,000원 제약)
    "album_test_1000": {"albums": 1, "price_krw": 1000, "price_usd": 100},
}

# 앨범 1개를 만들거나(체험 아님) 체험 앨범을 영구 전환할 때 소모되는 생성권 수.
ALBUM_UNLOCK_COST = 1


class InsufficientCreditsError(Exception):
    pass


class CreditService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def add_credits(
        self,
        user_id: uuid.UUID,
        package: str,
        reference_id: str | None = None,
    ) -> CreditTransaction:
        """앨범 생성권 충전 — 결제 성공 후 호출. SELECT FOR UPDATE로 동시성 보호."""
        pkg = PACKAGES.get(package)
        if not pkg:
            raise ValueError(f"Invalid package: {package}")

        result = await self.db.execute(
            select(User).where(User.id == user_id).with_for_update()
        )
        user = result.scalar_one()

        new_balance = user.credits + pkg["albums"]
        user.credits = new_balance

        tx = CreditTransaction(
            user_id=user_id,
            tx_type=TxType.PURCHASE,
            amount=pkg["albums"],
            balance_after=new_balance,
            description=f"Purchase {package}",
            reference_id=reference_id,
        )
        self.db.add(tx)
        await self.db.flush()
        return tx

    async def deduct_credits(
        self,
        user_id: uuid.UUID,
        tx_type: str,
        reference_id: str | None = None,
    ) -> CreditTransaction | None:
        """앨범 생성권 1개 소모 — 잔여 없으면 InsufficientCreditsError."""
        if tx_type != "album_create":
            raise ValueError(f"Invalid tx_type: {tx_type}")

        result = await self.db.execute(
            select(User).where(User.id == user_id).with_for_update()
        )
        user = result.scalar_one()

        if user.email and user.email in ADMIN_EMAILS:
            return None

        if user.credits < ALBUM_UNLOCK_COST:
            raise InsufficientCreditsError("결제가 필요합니다.")

        new_balance = user.credits - ALBUM_UNLOCK_COST
        user.credits = new_balance

        tx = CreditTransaction(
            user_id=user_id,
            tx_type=TxType.ALBUM_CREATE,
            amount=-ALBUM_UNLOCK_COST,
            balance_after=new_balance,
            description=f"Deduct for {tx_type}",
            reference_id=reference_id,
        )
        self.db.add(tx)
        await self.db.flush()
        return tx

    async def get_balance(self, user_id: uuid.UUID) -> int:
        result = await self.db.execute(
            select(User.credits).where(User.id == user_id)
        )
        return result.scalar_one()

    async def get_history(
        self, user_id: uuid.UUID, limit: int = 20
    ) -> list[CreditTransaction]:
        result = await self.db.execute(
            select(CreditTransaction)
            .where(CreditTransaction.user_id == user_id)
            .order_by(CreditTransaction.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
