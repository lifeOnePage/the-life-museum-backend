from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EmailVerification(Base):
    __tablename__ = "email_verifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    code: Mapped[str] = mapped_column(String(6), nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
