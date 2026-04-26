import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.record import Record
from app.models.user_record_association import UserRecordAssociation
from app.models.lifestory import Lifestory, Qa
from app.models.timeline import Timeline, Event
from app.models.cover_image import CoverImage
from app.schemas.scraper import MediaItem
from app.services.scraper import GooglePhotosScraper, ICloudScraper, MyBoxScraper
from app.services.google_photos_api import GooglePhotosAPI, AlbumMetadata
from app.core.exceptions import ConflictException, ForbiddenException, NotFoundException


logger = logging.getLogger(__name__)


class RecordService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_record(
        self,
        user_id: uuid.UUID,
        title: str,
        subtitle: str | None,
        google_photo_url: str | None,
        icloud_url: str | None,
        mybox_url: str | None,
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
            icloud_url=icloud_url,
            mybox_url=mybox_url,
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
                "어린 시절, 골목길을 누비며 뛰어놀던 기억이 아직도 생생합니다. "
                "여름이면 할머니 댁 마당에서 수박을 먹고, 겨울이면 온 동네가 하얗게 물든 눈밭 위를 걸었죠. "
                "그 시절의 따뜻한 햇살과 웃음소리가 지금의 저를 만들어 주었습니다."
            ),
        )
        self.db.add(lifestory)
        await self.db.flush()

        # 기본 타임라인
        timeline = Timeline(record_id=record.id)
        self.db.add(timeline)
        await self.db.flush()

        default_events = [
            {"title": "서울에서 태어남", "timestamp": "1995", "description": ""},
            {"title": "초등학교 입학 - 첫 번째 친구를 만남", "timestamp": "2001", "description": ""},
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
            ("icloud", record.icloud_url),
            ("mybox", record.mybox_url),
        ]

        scrapers = {
            "google_photos": GooglePhotosScraper,
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

        return items

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
