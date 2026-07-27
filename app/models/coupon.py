from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Coupon(Base):
    """쿠폰 — 두 타입.

    - credit: 코드 입력(redeem) 즉시 credit_amount 만큼 크레딧 지급 후 소모
    - discount: 코드 입력 시 유저 보관함에 등록(claim)되고, 크레딧 충전 결제에서
      discount_percent% 할인(최대 max_discount_krw, 원화 기준)을 적용하며 소모
    """

    __tablename__ = "coupons"

    # 기초 정보
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    code: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # 타입: 'credit' | 'discount'
    coupon_type: Mapped[str] = mapped_column(
        String(20), server_default="credit", nullable=False
    )

    # 크레딧 수량 (credit 타입 전용)
    credit_amount: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # 할인율(%)·상한금액(KRW) (discount 타입 전용)
    discount_percent: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_discount_krw: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # discount 타입: 보관함 등록 (결제 사용 전 단계)
    claimed_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    claimed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # 사용 여부 / 사용일 (credit: redeem 시, discount: 결제 성공 시)
    is_used: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), nullable=False
    )
    used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 사용한 유저 (운영 추적용)
    used_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    used_by = relationship(
        "User", foreign_keys=[used_by_user_id], backref="used_coupons"
    )
    claimed_by = relationship(
        "User", foreign_keys=[claimed_by_user_id], backref="claimed_coupons"
    )
