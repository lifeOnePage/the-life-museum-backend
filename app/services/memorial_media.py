"""Memorial 앨범 미디어 인제스트 — 선택된 미디어를 R2로 복사해 영속화.

일반 앨범과 달리 추모 앨범은 공유 링크를 스크래핑하지 않고, 생성/전환 시점에
고른 미디어(≤ MEMORIAL_MAX_MEDIA)를 원본에서 내려받아 R2에 보존한다.
소스 URL과 액세스 토큰은 DB에 저장하지 않는다 — pending 행 삽입 직후
같은 프로세스에서 create_task로 소비되는 인메모리 작업 목록으로만 전달
(프로세스 재시작 시 잔류 pending 행은 status 엔드포인트의 staleness 규칙이
failed로 집계한다).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass

import httpx
from sqlalchemy import select, update

from app.database import AsyncSessionLocal
from app.models.cover_image import CoverImage
from app.models.record import Record
from app.models.record_media import RecordMedia
from app.services.storage import R2StorageService
from app.services.url_policy import is_allowed_media_host
from app.services.video_transcoder import VideoTranscoderService

logger = logging.getLogger(__name__)

# Railway 메모리 보호: 동시 이미지 다운로드 상한 (비디오는 트랜스코더의
# 자체 Semaphore(2)가 제한)
_image_semaphore = asyncio.Semaphore(3)

# 레코드당 동시 인제스트 1개 (단일 워커 전제 — media_cache와 동일)
_active_ingests: set[uuid.UUID] = set()

_MAX_IMAGE_BYTES = 30 * 1024 * 1024
_DOWNLOAD_TIMEOUT = httpx.Timeout(60.0, connect=10.0)

_EXT_BY_CONTENT_TYPE = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/heic": "heic",
    "image/heif": "heif",
}


@dataclass
class IngestItem:
    row_id: uuid.UUID
    url: str
    media_type: str  # image | video


def is_ingest_active(record_id: uuid.UUID) -> bool:
    return record_id in _active_ingests


def picker_download_url(base_url: str, media_type: str) -> str:
    """피커 baseUrl → 실제 다운로드 URL (이미지 w2048, 비디오 =dv)."""
    suffix = "=dv" if media_type == "video" else "=w2048"
    return f"{base_url}{suffix}"


async def _download_image(url: str, headers: dict | None) -> tuple[bytes, str]:
    """이미지 스트리밍 다운로드 (크기 캡 포함). (bytes, content_type) 반환."""
    async with httpx.AsyncClient(
        timeout=_DOWNLOAD_TIMEOUT, headers=headers or {}, follow_redirects=True
    ) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            content_type = (
                resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
            )
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                total += len(chunk)
                if total > _MAX_IMAGE_BYTES:
                    raise ValueError(f"image exceeds {_MAX_IMAGE_BYTES} bytes")
                chunks.append(chunk)
            return b"".join(chunks), content_type


async def _set_row(row_id: uuid.UUID, **values) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(RecordMedia).where(RecordMedia.id == row_id).values(**values)
        )
        await db.commit()


async def _ingest_one(
    item: IngestItem,
    source: str,
    headers: dict | None,
    storage: R2StorageService,
    transcoder: VideoTranscoderService,
) -> None:
    await _set_row(item.row_id, status="processing")
    try:
        download_url = (
            picker_download_url(item.url, item.media_type)
            if source == "google_picker"
            else item.url
        )

        if item.media_type == "video":
            result = await transcoder.transcode_and_upload(
                download_url, headers=headers, with_poster=True
            )
            thumbnail_r2_url = None
            poster = result.get("poster_bytes")
            if poster:
                thumbnail_r2_url = await storage.upload_file(
                    poster, "image/jpeg", "jpg", prefix="memorial"
                )
            await _set_row(
                item.row_id,
                status="ready",
                r2_url=result["r2_url"],
                thumbnail_r2_url=thumbnail_r2_url,
                original_size_bytes=result.get("original_size_bytes"),
                error=None,
            )
        else:
            async with _image_semaphore:
                content, content_type = await _download_image(download_url, headers)
            ext = _EXT_BY_CONTENT_TYPE.get(content_type, "jpg")
            r2_url = await storage.upload_file(
                content, content_type, ext, prefix="memorial"
            )
            await _set_row(
                item.row_id,
                status="ready",
                r2_url=r2_url,
                original_size_bytes=len(content),
                error=None,
            )
    except Exception as e:
        logger.warning(
            "memorial ingest failed: row=%s url=%s err=%s",
            item.row_id,
            item.url[:100],
            e,
        )
        await _set_row(item.row_id, status="failed", error=str(e)[:500])


async def _finalize_cover(record_id: uuid.UUID) -> None:
    """커버가 없으면 첫 번째 ready 이미지로 자동 설정."""
    async with AsyncSessionLocal() as db:
        existing = (
            await db.execute(
                select(CoverImage.id).where(CoverImage.record_id == record_id)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return
        first_image_url = (
            await db.execute(
                select(RecordMedia.r2_url)
                .where(
                    RecordMedia.record_id == record_id,
                    RecordMedia.status == "ready",
                    RecordMedia.media_type == "image",
                )
                .order_by(RecordMedia.sort_order)
                .limit(1)
            )
        ).scalar_one_or_none()
        if not first_image_url:
            return
        db.add(CoverImage(record_id=record_id, url=first_image_url))
        await db.execute(
            update(Record)
            .where(Record.id == record_id)
            .values(back_cover_image_url=first_image_url)
        )
        await db.commit()


async def ingest(
    record_id: uuid.UUID,
    items: list[IngestItem],
    source: str,
    access_token: str | None = None,
) -> None:
    """백그라운드 인제스트 본체 — 행별 부분 성공 허용."""
    if record_id in _active_ingests:
        logger.warning("memorial ingest already active: record=%s", record_id)
        return
    _active_ingests.add(record_id)
    try:
        headers = (
            {"Authorization": f"Bearer {access_token}"}
            if source == "google_picker" and access_token
            else None
        )
        storage = R2StorageService()
        transcoder = VideoTranscoderService()

        # SSRF 가드: 허용되지 않은 호스트는 다운로드 전에 즉시 실패 처리
        valid_items: list[IngestItem] = []
        for item in items:
            if source != "upload" and not is_allowed_media_host(item.url):
                await _set_row(
                    item.row_id, status="failed", error="host not allowed"
                )
            else:
                valid_items.append(item)

        await asyncio.gather(
            *(
                _ingest_one(item, source, headers, storage, transcoder)
                for item in valid_items
            )
        )
        await _finalize_cover(record_id)
        logger.info(
            "memorial ingest done: record=%s total=%d", record_id, len(items)
        )
    finally:
        _active_ingests.discard(record_id)
