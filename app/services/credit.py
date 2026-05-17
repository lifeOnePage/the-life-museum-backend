from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.credit import CreditTransaction, TxType

PACKAGES = {
    "credit_1000": {"credits": 1000, "price_krw": 10000, "price_usd": 999},
    "credit_3900": {"credits": 3900, "price_krw": 29000, "price_usd": 2499},
    "credit_9900": {"credits": 9900, "price_krw": 59000, "price_usd": 4999},
}

COSTS = {
    "album_create": 900,
    "emoji_regular": 100,
    "emoji_limited": 200,
}


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
        """크레딧 충전 — 결제 성공 후 호출. SELECT FOR UPDATE로 동시성 보호."""
        pkg = PACKAGES.get(package)
        if not pkg:
            raise ValueError(f"Invalid package: {package}")

        result = await self.db.execute(
            select(User).where(User.id == user_id).with_for_update()
        )
        user = result.scalar_one()

        new_balance = user.credits + pkg["credits"]
        user.credits = new_balance

        tx = CreditTransaction(
            user_id=user_id,
            tx_type=TxType.PURCHASE,
            amount=pkg["credits"],
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
    ) -> CreditTransaction:
        """크레딧 차감 — 잔액 부족 시 InsufficientCreditsError."""
        cost = COSTS.get(tx_type)
        if cost is None:
            raise ValueError(f"Invalid tx_type: {tx_type}")

        result = await self.db.execute(
            select(User).where(User.id == user_id).with_for_update()
        )
        user = result.scalar_one()

        if user.credits < cost:
            raise InsufficientCreditsError(
                f"Need {cost}, have {user.credits}"
            )

        new_balance = user.credits - cost
        user.credits = new_balance

        # tx_type 문자열에서 TxType enum 매핑
        if tx_type.startswith("emoji_"):
            enum_type = TxType.EMOJI_BUY
        else:
            enum_type = TxType(tx_type)

        tx = CreditTransaction(
            user_id=user_id,
            tx_type=enum_type,
            amount=-cost,
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
