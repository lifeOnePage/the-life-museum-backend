import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.record import Record
from app.models.lifestory import Lifestory, Qa
from app.models.timeline import Timeline, Event
from app.models.cover_image import CoverImage
from app.services.scraper import GooglePhotosScraper, ICloudScraper, MyBoxScraper


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
        record = Record(
            user_id=user_id,
            creator_id=user_id,
            title=title,
            subtitle=subtitle,
            google_photo_url=google_photo_url,
            icloud_url=icloud_url,
            mybox_url=mybox_url,
        )
        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)
        return record

    async def get_records_by_user(self, user_id: uuid.UUID) -> list[Record]:
        stmt = (
            select(Record)
            .options(selectinload(Record.cover_image))
            .where(Record.user_id == user_id)
            .order_by(Record.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

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

    async def scrape_media_list(self, record: Record) -> list[str]:
        urls: list[str] = []
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
                continue
            try:
                scraper = scrapers[provider]()
                media_items = await scraper.scrape(url)
                for item in media_items:
                    urls.append(item.original_url)
            except Exception:
                continue

        return urls

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
