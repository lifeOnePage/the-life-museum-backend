from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.record import Record


class Lifestory(Base):
    __tablename__ = "lifestories"
    __table_args__ = (
        UniqueConstraint("record_id", name="uq_lifestories_record_id"),
    )

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

    mood: Mapped[str] = mapped_column(String(100), nullable=False)
    
    content: Mapped[str] = mapped_column(String(350), nullable=False)

    # 관계: Lifestory(1) - Record(1)
    record: Mapped["Record"] = relationship("Record", back_populates="lifestory")

    # 관계: Lifestory(1) - Qa(N)
    qas: Mapped[List["Qa"]] = relationship(
        "Qa",
        back_populates="lifestory",
        cascade="all, delete-orphan",
    )


class Qa(Base):
    __tablename__ = "qas"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    lifestory_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lifestories.id", ondelete="CASCADE"),
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

    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)

    # 관계: Qa(N) - Lifestory(1)
    lifestory: Mapped["Lifestory"] = relationship("Lifestory", back_populates="qas")
