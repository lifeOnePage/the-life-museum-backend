from __future__ import annotations

import uuid

import httpx
import stripe
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.payment import Payment, PaymentStatus


class PaymentVerificationError(Exception):
    pass


class PaymentService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def verify_stripe(
        self, user_id: uuid.UUID, session_id: str
    ) -> Payment:
        """Stripe Checkout Session 검증 후 Payment 레코드 저장."""
        # Idempotency: 이미 검증된 결제면 기존 레코드 반환
        existing = await self._find_by_tx_id(session_id)
        if existing:
            return existing

        stripe.api_key = settings.STRIPE_SECRET_KEY
        try:
            session = stripe.checkout.Session.retrieve(session_id)
        except stripe.InvalidRequestError as e:
            raise PaymentVerificationError(f"Invalid session: {e}")

        if session.payment_status != "paid":
            payment = Payment(
                user_id=user_id,
                gateway="stripe",
                gateway_tx_id=session_id,
                amount=session.amount_total,
                currency=session.currency,
                package=session.metadata.get("package") if session.metadata else None,
                status=PaymentStatus.FAILED,
            )
            self.db.add(payment)
            await self.db.flush()
            raise PaymentVerificationError(
                f"Payment not completed. Status: {session.payment_status}"
            )

        payment = Payment(
            user_id=user_id,
            gateway="stripe",
            gateway_tx_id=session_id,
            amount=session.amount_total,
            currency=session.currency,
            package=session.metadata.get("package") if session.metadata else None,
            status=PaymentStatus.CONFIRMED,
        )
        self.db.add(payment)
        await self.db.flush()
        return payment

    async def verify_portone(
        self,
        user_id: uuid.UUID,
        imp_uid: str,
        merchant_uid: str | None = None,
    ) -> Payment:
        """PortOne(iamport) 결제 검증 후 Payment 레코드 저장."""
        # Idempotency
        existing = await self._find_by_tx_id(imp_uid)
        if existing:
            return existing

        access_token = await self._get_portone_token()

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"https://api.iamport.kr/payments/{imp_uid}",
                headers={"Authorization": access_token},
            )

        if resp.status_code != 200:
            raise PaymentVerificationError(
                f"PortOne API error: {resp.status_code}"
            )

        data = resp.json()
        pay_response = data.get("response")
        if not pay_response:
            raise PaymentVerificationError("Empty response from PortOne")

        pay_status = pay_response.get("status")
        amount = pay_response.get("amount")
        currency = pay_response.get("currency", "KRW").lower()

        if pay_status != "paid":
            payment = Payment(
                user_id=user_id,
                gateway="portone",
                gateway_tx_id=imp_uid,
                amount=amount,
                currency=currency,
                status=PaymentStatus.FAILED,
            )
            self.db.add(payment)
            await self.db.flush()
            raise PaymentVerificationError(
                f"Payment not paid. Status: {pay_status}"
            )

        payment = Payment(
            user_id=user_id,
            gateway="portone",
            gateway_tx_id=imp_uid,
            amount=amount,
            currency=currency,
            status=PaymentStatus.CONFIRMED,
        )
        self.db.add(payment)
        await self.db.flush()
        return payment

    async def _get_portone_token(self) -> str:
        """PortOne REST API 토큰 발급."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.iamport.kr/users/getToken",
                json={
                    "imp_key": settings.PORTONE_API_KEY,
                    "imp_secret": settings.PORTONE_API_SECRET,
                },
            )

        if resp.status_code != 200:
            raise PaymentVerificationError("Failed to get PortOne token")

        data = resp.json()
        token = data.get("response", {}).get("access_token")
        if not token:
            raise PaymentVerificationError("Empty PortOne token")
        return token

    async def _find_by_tx_id(self, gateway_tx_id: str) -> Payment | None:
        """기존 결제 레코드 조회 (idempotency)."""
        result = await self.db.execute(
            select(Payment).where(Payment.gateway_tx_id == gateway_tx_id)
        )
        return result.scalar_one_or_none()
