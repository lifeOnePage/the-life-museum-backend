from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.record import Record


class VideoCache(Base):
    __tablename__ = "video_cache"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    # SHA256 hash of the base Google Photos lh3 URL (without parameters)
    source_url_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )

    record_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("records.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # R2 URL for the optimized 720p faststart MP4
    r2_url: Mapped[str] = mapped_column(Text, nullable=False)

    original_size_bytes: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True
    )
    optimized_size_bytes: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True
    )
    duration_seconds: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )

    # pending | processing | ready | failed
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'pending'")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    record: Mapped[Optional["Record"]] = relationship(
        "Record", foreign_keys=[record_id]
    )
