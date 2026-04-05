from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.cover_image import CoverImage
    from app.models.lifestory import Lifestory
    from app.models.timeline import Timeline
    from app.models.user import User
    from app.models.user_record_association import UserRecordAssociation


class Record(Base):
    __tablename__ = "records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    creator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
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

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    subtitle: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # 컬러 설정
    color: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)
    bg_color: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)
    key_color: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)

    # 테마
    theme: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # 커버 제목 설정
    cover_title_visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    cover_title_position: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'center-center'")
    )
    cover_title_font: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )
    cover_title_color: Mapped[Optional[str]] = mapped_column(
        String(7), nullable=True
    )

    # 커버 생성 횟수 (최대 3회)
    cover_gen_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )

    # 외부 저장소 URL
    google_photo_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    icloud_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    mybox_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    public_access_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 비공개 접근 계정 목록 (PostgreSQL ARRAY)
    private_access_accounts: Mapped[List[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'::text[]"),
    )

    # 관계: Record(N) - User(1) (생성자)
    creator: Mapped["User"] = relationship(
        "User",
        back_populates="created_records",
        foreign_keys=[creator_id],
    )

    # 관계: Record(N) - UserRecordAssociation(N)
    user_associations: Mapped[List["UserRecordAssociation"]] = relationship(
        "UserRecordAssociation",
        back_populates="record",
        cascade="all, delete-orphan",
    )

    # 관계: Record(1) - CoverImage(0..1)
    cover_image: Mapped[Optional["CoverImage"]] = relationship(
        "CoverImage",
        back_populates="record",
        cascade="all, delete-orphan",
        uselist=False,
    )

    # 관계: Record(1) - Timeline(0..1)
    timeline: Mapped[Optional["Timeline"]] = relationship(
        "Timeline",
        back_populates="record",
        cascade="all, delete-orphan",
        uselist=False,
    )

    # 관계: Record(1) - Lifestory(0..1)
    lifestory: Mapped[Optional["Lifestory"]] = relationship(
        "Lifestory",
        back_populates="record",
        cascade="all, delete-orphan",
        uselist=False,
    )
