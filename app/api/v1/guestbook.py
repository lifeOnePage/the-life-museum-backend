from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, NotFoundException
from app.database import get_db
from app.models.guestbook_entry import GuestbookEntry
from app.models.record import Record
from app.schemas.common import ApiResponse, success_response
from app.schemas.guestbook import (
    GuestbookCreateResponse,
    GuestbookEntryCreate,
    GuestbookEntryItem,
    GuestbookListResponse,
)

router = APIRouter()

# 레코드당 방명록 최대 개수 — 비인증 공개 엔드포인트의 무한 적재 방지
MAX_ENTRIES_PER_RECORD = 1000


def _to_item(entry: GuestbookEntry) -> GuestbookEntryItem:
    return GuestbookEntryItem(
        id=entry.id,
        authorName=entry.author_name,
        flowerType=entry.flower_type,
        message=entry.message,
        createdAt=entry.created_at,
    )


async def _ensure_record_exists(db: AsyncSession, record_id: uuid.UUID) -> None:
    # RecordService.get_record_by_id는 관계 3개를 selectinload하므로
    # 존재 확인만 필요한 여기서는 경량 조회를 쓴다
    exists = (
        await db.execute(select(Record.id).where(Record.id == record_id))
    ).scalar_one_or_none()
    if exists is None:
        raise NotFoundException("Record not found")


@router.get("/{record_id}/guestbook", response_model=ApiResponse)
async def list_guestbook(
    record_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """방명록 목록 조회 (공개 — 감상 페이지에서 인증 없이 호출)."""
    await _ensure_record_exists(db, record_id)

    total = (
        await db.execute(
            select(func.count(GuestbookEntry.id)).where(
                GuestbookEntry.record_id == record_id
            )
        )
    ).scalar_one()

    result = await db.execute(
        select(GuestbookEntry)
        .where(GuestbookEntry.record_id == record_id)
        .order_by(GuestbookEntry.created_at.desc(), GuestbookEntry.id.desc())
        .limit(limit)
        .offset(offset)
    )
    entries = result.scalars().all()

    return success_response(
        data=GuestbookListResponse(
            entries=[_to_item(e) for e in entries],
            total=total,
        )
    )


@router.post("/{record_id}/guestbook", response_model=ApiResponse)
async def create_guestbook_entry(
    record_id: uuid.UUID,
    body: GuestbookEntryCreate,
    db: AsyncSession = Depends(get_db),
):
    """방명록 작성 (공개 — 방문자가 인증 없이 남긴다)."""
    enabled = (
        await db.execute(
            select(Record.guestbook_enabled).where(Record.id == record_id)
        )
    ).scalar_one_or_none()
    if enabled is None:
        raise NotFoundException("Record not found")
    if not enabled:
        raise BadRequestException("Guestbook is disabled for this record")

    total = (
        await db.execute(
            select(func.count(GuestbookEntry.id)).where(
                GuestbookEntry.record_id == record_id
            )
        )
    ).scalar_one()
    if total >= MAX_ENTRIES_PER_RECORD:
        raise BadRequestException("Guestbook is full")

    entry = GuestbookEntry(
        record_id=record_id,
        author_name=body.authorName,
        flower_type=body.flowerType,
        message=body.message,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)

    return success_response(
        data=GuestbookCreateResponse(entry=_to_item(entry), total=total + 1)
    )
