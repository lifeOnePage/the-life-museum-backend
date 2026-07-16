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
    """크레딧 쿠폰. 코드 입력으로 1회 사용하면 credit_amount 만큼 크레딧 지급."""

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

    # 크레딧 수량
    credit_amount: Mapped[int] = mapped_column(Integer, nullable=False)

    # 사용 여부 / 사용일
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

    used_by = relationship("User", backref="used_coupons")
