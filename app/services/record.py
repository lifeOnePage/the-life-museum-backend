import asyncio
import logging
import queue as thread_queue
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.record import Record
from app.models.user_record_association import UserRecordAssociation
from app.models.lifestory import Lifestory, Qa
from app.models.timeline import Timeline, Event
from app.models.cover_image import CoverImage
from app.models.video_cache import VideoCache
from app.schemas.scraper import MediaItem, MediaType
from app.services.scraper import (
    GoogleDriveScraper,
    GooglePhotosScraper,
    ICloudScraper,
    MyBoxScraper,
)
from app.services.google_photos_api import GooglePhotosAPI, AlbumMetadata
from app.services.video_transcoder import (
    VideoTranscoderService,
    compute_source_url_hash,
)
from app.core.exceptions import ConflictException, ForbiddenException, NotFoundException


logger = logging.getLogger(__name__)


class RecordService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def count_owned_records(self, user_id: uuid.UUID) -> int:
        """사용자가 생성한(소유) 앨범 수."""
        from sqlalchemy import func

        result = await self.db.execute(
            select(func.count())
            .select_from(Record)
            .where(Record.creator_id == user_id)
        )
        return result.scalar_one()

    async def create_record(
        self,
        user_id: uuid.UUID,
        title: str,
        subtitle: str | None,
        google_photo_url: str | None,
        google_drive_url: str | None,
        icloud_url: str | None,
        mybox_url: str | None,
        is_trial: bool = False,
    ) -> Record:
        # Google Photos 메타데이터 자동 채움
        album_meta: AlbumMetadata | None = None
        if google_photo_url:
            album_meta = await self._fetch_google_album_metadata(google_photo_url)

        if album_meta and (not title or not title.strip()):
            title = album_meta.title or title
        if album_meta and album_meta.subtitle and (not subtitle or not subtitle.strip()):
            subtitle = album_meta.subtitle

        record = Record(
            creator_id=user_id,
            title=title,
            subtitle=subtitle,
            google_photo_url=google_photo_url,
            google_drive_url=google_drive_url,
            icloud_url=icloud_url,
            mybox_url=mybox_url,
            is_trial=is_trial,
        )
        self.db.add(record)
        await self.db.flush()

        # 커버 이미지 자동 생성 (R2에 재업로드하여 CORS 문제 방지)
        if album_meta and album_meta.cover_photo_bytes:
            from app.services.storage import R2StorageService
            storage = R2StorageService()
            content_type = album_meta.cover_photo_content_type or "image/jpeg"
            ext = content_type.split("/")[-1].replace("jpeg", "jpg")
            r2_url = await storage.upload_file(album_meta.cover_photo_bytes, content_type, ext)
            cover = CoverImage(record_id=record.id, url=r2_url)
            self.db.add(cover)
        elif album_meta and album_meta.cover_photo_url:
            cover = CoverImage(record_id=record.id, url=album_meta.cover_photo_url)
            self.db.add(cover)

        assoc = UserRecordAssociation(user_id=user_id, record_id=record.id, role="owner")
        self.db.add(assoc)

        # 기본 라이프스토리
        lifestory = Lifestory(
            record_id=record.id,
            mood="",
            content=(
               "We do not remember days, we remember moments."
            ),
        )
        self.db.add(lifestory)
        await self.db.flush()

        # 기본 타임라인
        timeline = Timeline(record_id=record.id)
        self.db.add(timeline)
        await self.db.flush()

        default_events = [
            {"title": "The Life Gallery", "timestamp": "2026", "description": "The Life Gallery"},
        ]
        for evt_data in default_events:
            self.db.add(Event(
                timeline_id=timeline.id,
                title=evt_data["title"],
                timestamp=evt_data["timestamp"],
                description=evt_data["description"],
            ))

        await self.db.commit()
        await self.db.refresh(record, attribute_names=["cover_image"])

        # Pre-transcoding: scrape videos from the album and start transcoding
        # in the background so optimized files are ready before the first visit.
        if google_photo_url:
            asyncio.create_task(
                self._pretranscode_album_videos(record.id, google_photo_url)
            )

        return record

    async def _fetch_google_album_metadata(
        self, google_photo_url: str
    ) -> AlbumMetadata | None:
        """공유 앨범 URL의 OG 메타태그에서 메타데이터 추출. 실패 시 None."""
        try:
            api = GooglePhotosAPI()
            return await api.get_album_metadata(share_url=google_photo_url)
        except Exception as e:
            logger.warning("Failed to fetch Google album metadata: %s", e)
            return None

    async def update_record(
        self,
        record: Record,
        update_data: dict,
    ) -> Record:
        for field, value in update_data.items():
            setattr(record, field, value)
        await self.db.commit()
        await self.db.refresh(record)
        return record

    async def get_user_association(
        self, user_id: uuid.UUID, record_id: uuid.UUID
    ) -> UserRecordAssociation | None:
        stmt = select(UserRecordAssociation).where(
            UserRecordAssociation.user_id == user_id,
            UserRecordAssociation.record_id == record_id,
        )
        return await self.db.scalar(stmt)

    async def get_records_by_user(self, user_id: uuid.UUID) -> list[tuple[Record, str]]:
        stmt = (
            select(Record, UserRecordAssociation.role)
            .join(UserRecordAssociation, UserRecordAssociation.record_id == Record.id)
            .where(UserRecordAssociation.user_id == user_id)
            .options(
                selectinload(Record.cover_image),
                selectinload(Record.lifestory),
                selectinload(Record.timeline).selectinload(Timeline.events),
            )
            .order_by(Record.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]

    async def get_record_by_id(self, record_id: uuid.UUID) -> Record | None:
        stmt = (
            select(Record)
            .options(
                selectinload(Record.cover_image),
                selectinload(Record.lifestory).selectinload(Lifestory.qas),
                selectinload(Record.timeline).selectinload(Timeline.events),
            )
            .where(Record.id == record_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def scrape_media_list(self, record: Record) -> list[MediaItem]:
        items: list[MediaItem] = []
        source_urls = [
            ("google_photos", record.google_photo_url),
            ("google_drive", record.google_drive_url),
            ("icloud", record.icloud_url),
            ("mybox", record.mybox_url),
        ]

        scrapers = {
            "google_photos": GooglePhotosScraper,
            "google_drive": GoogleDriveScraper,
            "icloud": ICloudScraper,
            "mybox": MyBoxScraper,
        }

        for provider, url in source_urls:
            if not url:
                logger.warning("Skipping provider=%s: url is empty/None", provider)
                continue
            try:
                logger.warning("Scraping provider=%s url=%s", provider, url)
                scraper = scrapers[provider]()
                media_items = await scraper.scrape(url)
                logger.warning("Scraping result provider=%s: %d items", provider, len(media_items))
                items.extend(media_items)
            except Exception as e:
                logger.error("Scraping failed for provider=%s url=%s: %s", provider, url, e)
                continue

        # ── Video cache: swap original URLs for optimized R2 URLs ──
        items = await self._apply_video_cache(items, record.id)

        return items

    @staticmethod
    async def scrape_media_list_stream_standalone(record_snapshot: dict):
        """
        SSE로 스크래핑 진행 상황 스트리밍 (DB 세션 미사용).

        record_snapshot: {"id", "google_photo_url", "google_drive_url", "icloud_url", "mybox_url"}
        스크래핑은 외부 HTTP 요청만 수행하므로 DB 불필요.
        _apply_video_cache만 별도 세션을 짧게 열어 처리.
        """
        from app.database import AsyncSessionLocal

        items: list[MediaItem] = []
        source_urls = [
            ("google_photos", record_snapshot["google_photo_url"]),
            ("google_drive", record_snapshot["google_drive_url"]),
            ("icloud", record_snapshot["icloud_url"]),
            ("mybox", record_snapshot["mybox_url"]),
        ]
        scrapers = {
            "google_photos": GooglePhotosScraper,
            "google_drive": GoogleDriveScraper,
            "icloud": ICloudScraper,
            "mybox": MyBoxScraper,
        }

        active_sources = [(p, u) for p, u in source_urls if u]
        total = len(active_sources)

        yield {"type": "progress", "phase": "started", "totalSources": total}

        for idx, (provider, url) in enumerate(active_sources):
            yield {"type": "progress", "phase": "scraping",
                   "source": provider, "sourceIndex": idx, "totalSources": total}
            try:
                scraper = scrapers[provider]()
                progress_q = thread_queue.Queue()

                def progress_cb(event, _q=progress_q):
                    _q.put(event)

                scrape_task = asyncio.create_task(
                    scraper.scrape(url, progress_callback=progress_cb)
                )

                # Poll queue for intermediate progress events while scraping
                while not scrape_task.done():
                    await asyncio.sleep(0.2)
                    while not progress_q.empty():
                        try:
                            event = progress_q.get_nowait()
                            yield {"type": "progress", "phase": "scraping_detail",
                                   "source": provider, "sourceIndex": idx,
                                   "totalSources": total, **event}
                        except thread_queue.Empty:
                            break

                media_items = scrape_task.result()

                # Drain any remaining events
                while not progress_q.empty():
                    try:
                        event = progress_q.get_nowait()
                        yield {"type": "progress", "phase": "scraping_detail",
                               "source": provider, "sourceIndex": idx,
                               "totalSources": total, **event}
                    except thread_queue.Empty:
                        break

                items.extend(media_items)
                yield {"type": "progress", "phase": "source_done",
                       "source": provider, "sourceIndex": idx, "totalSources": total,
                       "itemsFound": len(media_items)}
            except Exception as e:
                logger.error("Scraping failed: provider=%s error=%s", provider, e)
                yield {"type": "progress", "phase": "source_error",
                       "source": provider, "sourceIndex": idx, "totalSources": total}

        yield {"type": "progress", "phase": "optimizing"}

        # Open a short-lived DB session only for video cache lookup
        record_id = record_snapshot["id"]
        async with AsyncSessionLocal() as db:
            service = RecordService(db)
            items = await service._apply_video_cache(items, record_id)

        yield {"type": "complete",
               "mediaList": [item.model_dump() for item in items]}

    async def _apply_video_cache(
        self, items: list[MediaItem], record_id: uuid.UUID
    ) -> list[MediaItem]:
        """
        For video items, check video_cache for ready R2 URLs.
        If cached: swap original_url → R2 URL (720p faststart).
        If not cached: start background transcoding, return original URL (fallback).
        """
        video_items = [i for i in items if i.type == MediaType.VIDEO]
        if not video_items:
            return items

        # Batch-lookup all video hashes
        hashes = {
            compute_source_url_hash(v.original_url): v for v in video_items
        }
        stmt = select(VideoCache).where(
            VideoCache.source_url_hash.in_(list(hashes.keys()))
        )
        result = await self.db.execute(stmt)
        cached = {row.source_url_hash: row for row in result.scalars().all()}

        # Collect URLs that need transcoding
        urls_to_transcode: list[str] = []

        result_items: list[MediaItem] = []
        for item in items:
            if item.type != MediaType.VIDEO:
                result_items.append(item)
                continue

            url_hash = compute_source_url_hash(item.original_url)
            cache_entry = cached.get(url_hash)

            if cache_entry and cache_entry.status == "ready":
                # Cache hit: use optimized R2 URL
                result_items.append(MediaItem(
                    type=item.type,
                    thumbnail_url=item.thumbnail_url,
                    original_url=cache_entry.r2_url,
                ))
            else:
                # Cache miss or still processing: return original URL as fallback
                result_items.append(item)
                if not cache_entry:
                    urls_to_transcode.append(item.original_url)

        # Start background transcoding for uncached videos
        if urls_to_transcode:
            asyncio.create_task(
                self._background_transcode_videos(urls_to_transcode, record_id)
            )

        return result_items

    @staticmethod
    async def _background_transcode_videos(
        urls: list[str], record_id: uuid.UUID
    ) -> None:
        """Background task: transcode videos and save to cache DB."""
        from app.database import AsyncSessionLocal

        transcoder = VideoTranscoderService()

        for url in urls:
            url_hash = compute_source_url_hash(url)
            try:
                async with AsyncSessionLocal() as db:
                    # Check if another task already started this
                    existing = await db.scalar(
                        select(VideoCache).where(
                            VideoCache.source_url_hash == url_hash
                        )
                    )
                    if existing:
                        continue

                    # Create pending record
                    cache_entry = VideoCache(
                        source_url_hash=url_hash,
                        record_id=record_id,
                        r2_url="",
                        status="processing",
                    )
                    db.add(cache_entry)
                    await db.commit()
                    await db.refresh(cache_entry)

                # Transcode (outside DB session — long-running)
                result = await transcoder.transcode_and_upload(url, record_id)

                async with AsyncSessionLocal() as db:
                    entry = await db.scalar(
                        select(VideoCache).where(
                            VideoCache.source_url_hash == url_hash
                        )
                    )
                    if entry:
                        entry.r2_url = result["r2_url"]
                        entry.original_size_bytes = result["original_size_bytes"]
                        entry.optimized_size_bytes = result["optimized_size_bytes"]
                        entry.duration_seconds = result["duration_seconds"]
                        entry.status = "ready"
                        await db.commit()

                logger.info(
                    "Video transcoded: hash=%s r2_url=%s",
                    url_hash[:12],
                    result["r2_url"],
                )

            except Exception as e:
                logger.error(
                    "Background transcoding failed: hash=%s url=%s error=%s",
                    url_hash[:12],
                    url[:80],
                    e,
                )
                # Mark as failed
                try:
                    async with AsyncSessionLocal() as db:
                        entry = await db.scalar(
                            select(VideoCache).where(
                                VideoCache.source_url_hash == url_hash
                            )
                        )
                        if entry:
                            entry.status = "failed"
                            await db.commit()
                except Exception:
                    pass

    @staticmethod
    async def _pretranscode_album_videos(
        record_id: uuid.UUID, google_photo_url: str
    ) -> None:
        """Scrape Google Photos album for videos and start transcoding immediately."""
        try:
            scraper = GooglePhotosScraper()
            media_items = await scraper.scrape(google_photo_url)
            video_urls = [
                item.original_url
                for item in media_items
                if item.type == MediaType.VIDEO
            ]
            if video_urls:
                logger.info(
                    "Pre-transcoding %d videos for record=%s",
                    len(video_urls),
                    record_id,
                )
                await RecordService._background_transcode_videos(
                    video_urls, record_id
                )
        except Exception as e:
            logger.error(
                "Pre-transcoding failed for record=%s: %s", record_id, e
            )

    async def get_lifestory(self, record_id: uuid.UUID) -> Lifestory | None:
        stmt = (
            select(Lifestory)
            .options(selectinload(Lifestory.qas))
            .where(Lifestory.record_id == record_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def save_lifestory(
        self,
        record_id: uuid.UUID,
        qa_list: list[dict],
        mood: str,
        result_text: str,
    ) -> Lifestory:
        existing = await self.get_lifestory(record_id)

        if existing:
            existing.mood = mood
            existing.content = result_text

            # 기존 qa 삭제 후 새로 생성
            for qa in list(existing.qas):
                await self.db.delete(qa)

            for qa_data in qa_list:
                qa = Qa(
                    lifestory_id=existing.id,
                    question=qa_data["question"],
                    answer=qa_data["answer"],
                )
                self.db.add(qa)

            await self.db.commit()
            await self.db.refresh(existing)
            # reload qas
            stmt = (
                select(Lifestory)
                .options(selectinload(Lifestory.qas))
                .where(Lifestory.id == existing.id)
            )
            res = await self.db.execute(stmt)
            return res.scalar_one()
        else:
            lifestory = Lifestory(
                record_id=record_id,
                mood=mood,
                content=result_text,
            )
            self.db.add(lifestory)
            await self.db.flush()

            for qa_data in qa_list:
                qa = Qa(
                    lifestory_id=lifestory.id,
                    question=qa_data["question"],
                    answer=qa_data["answer"],
                )
                self.db.add(qa)

            await self.db.commit()
            await self.db.refresh(lifestory)
            stmt = (
                select(Lifestory)
                .options(selectinload(Lifestory.qas))
                .where(Lifestory.id == lifestory.id)
            )
            res = await self.db.execute(stmt)
            return res.scalar_one()

    async def save_timeline(
        self, record_id: uuid.UUID, events_data: list[dict]
    ) -> Timeline:
        stmt = select(Timeline).where(Timeline.record_id == record_id)
        result = await self.db.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            # 기존 이벤트 삭제
            evt_stmt = select(Event).where(Event.timeline_id == existing.id)
            evt_result = await self.db.execute(evt_stmt)
            for evt in evt_result.scalars().all():
                await self.db.delete(evt)

            for evt_data in events_data:
                event = Event(
                    timeline_id=existing.id,
                    title=evt_data["title"],
                    timestamp=evt_data["timestamp"],
                    description=evt_data["description"],
                )
                self.db.add(event)

            await self.db.commit()
            await self.db.refresh(existing)
            stmt = (
                select(Timeline)
                .options(selectinload(Timeline.events))
                .where(Timeline.id == existing.id)
            )
            res = await self.db.execute(stmt)
            return res.scalar_one()
        else:
            timeline = Timeline(record_id=record_id)
            self.db.add(timeline)
            await self.db.flush()

            for evt_data in events_data:
                event = Event(
                    timeline_id=timeline.id,
                    title=evt_data["title"],
                    timestamp=evt_data["timestamp"],
                    description=evt_data["description"],
                )
                self.db.add(event)

            await self.db.commit()
            await self.db.refresh(timeline)
            stmt = (
                select(Timeline)
                .options(selectinload(Timeline.events))
                .where(Timeline.id == timeline.id)
            )
            res = await self.db.execute(stmt)
            return res.scalar_one()

    async def delete_record(self, user_id: uuid.UUID, record_id: uuid.UUID) -> None:
        """소유자(owner)만 레코드 삭제 가능."""
        record = await self.get_record_by_id(record_id)
        if not record:
            raise NotFoundException("Record not found")

        # association 테이블 우선 확인, 없으면 creator_id로 폴백 (테이블 도입 이전 레코드 호환)
        assoc = await self.db.scalar(
            select(UserRecordAssociation).where(
                UserRecordAssociation.user_id == user_id,
                UserRecordAssociation.record_id == record_id,
                UserRecordAssociation.role == "owner",
            )
        )
        is_owner = (assoc is not None) or (record.creator_id == user_id)
        if not is_owner:
            raise ForbiddenException("Only the owner can delete this record")

        await self.db.delete(record)
        await self.db.commit()

    async def share_record(self, user_id: uuid.UUID, record_id: uuid.UUID) -> Record:
        """공유 앨범 추가: 이미 연관되어 있으면 Conflict."""
        record = await self.get_record_by_id(record_id)
        if not record:
            raise NotFoundException("Record not found")

        existing = await self.get_user_association(user_id, record_id)
        if existing:
            raise ConflictException("Already associated with this record")

        assoc = UserRecordAssociation(user_id=user_id, record_id=record_id, role="shared")
        self.db.add(assoc)
        await self.db.commit()
        return record

    async def unshare_record(self, user_id: uuid.UUID, record_id: uuid.UUID) -> None:
        """공유 제거: role='shared'인 연관만 삭제."""
        assoc = await self.db.scalar(
            select(UserRecordAssociation).where(
                UserRecordAssociation.user_id == user_id,
                UserRecordAssociation.record_id == record_id,
                UserRecordAssociation.role == "shared",
            )
        )
        if not assoc:
            raise NotFoundException("Shared record association not found")

        await self.db.delete(assoc)
        await self.db.commit()

    async def save_cover_image(self, record_id: uuid.UUID, url: str) -> CoverImage:
        stmt = select(CoverImage).where(CoverImage.record_id == record_id)
        result = await self.db.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            existing.url = url
            await self.db.commit()
            await self.db.refresh(existing)
            return existing
        else:
            cover = CoverImage(record_id=record_id, url=url)
            self.db.add(cover)
            await self.db.commit()
            await self.db.refresh(cover)
            return cover
