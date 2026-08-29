from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RecordMedia(Base):
    """추모(memorial) 앨범의 큐레이션·영속 미디어.

    일반 앨범은 공유 링크를 매 요청 스크래핑하지만, 추모 앨범은 생성/전환
    시점에 고른 미디어를 R2로 복사해 이 테이블에 영구 보존한다.
    상태 수명주기는 VideoCache와 동일: pending → processing → ready | failed.
    """

    __tablename__ = "record_media"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    record_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # image | video
    media_type: Mapped[str] = mapped_column(String(10), nullable=False)

    # R2 영속 URL — ready 전에는 NULL
    r2_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 비디오의 ffmpeg 포스터 프레임. 이미지는 NULL (읽기 시 r2_url로 폴백)
    thumbnail_r2_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)

    # google_picker | conversion | upload
    source: Mapped[str] = mapped_column(String(20), nullable=False)

    # pending | processing | ready | failed
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'pending'")
    )
    # 실패 사유 (디버깅용, 짧게 저장)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    original_size_bytes: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True
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
