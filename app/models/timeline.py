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


class Timeline(Base):
    __tablename__ = "timelines"
    __table_args__ = (
        UniqueConstraint("record_id", name="uq_timelines_record_id"),
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

    # 관계: Timeline(1) - Record(1)
    record: Mapped["Record"] = relationship("Record", back_populates="timeline")

    # 관계: Timeline(1) - Event(N)
    events: Mapped[List["Event"]] = relationship(
        "Event",
        back_populates="timeline",
        cascade="all, delete-orphan",
    )


class Event(Base):
    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    timeline_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("timelines.id", ondelete="CASCADE"),
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
    timestamp: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 관계: Event(N) - Timeline(1)
    timeline: Mapped["Timeline"] = relationship("Timeline", back_populates="events")
