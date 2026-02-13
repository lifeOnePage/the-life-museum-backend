from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.scraper import MediaItem


# --- QA ---
class QaItem(BaseModel):
    question: str
    answer: str


# --- Record ---
class RecordCreate(BaseModel):
    title: str
    subTitle: str | None = None
    googlePhotoUrl: str | None = None
    icloudUrl: str | None = None
    myboxUrl: str | None = None


class RecordUpdate(BaseModel):
    title: str | None = None
    subTitle: str | None = None
    googlePhotoUrl: str | None = None
    icloudUrl: str | None = None
    myboxUrl: str | None = None


class RecordResponse(BaseModel):
    id: uuid.UUID
    title: str
    subtitle: str | None = None
    googlePhotoUrl: str | None = None
    icloudUrl: str | None = None
    myboxUrl: str | None = None
    createdAt: datetime
    updatedAt: datetime

    model_config = {"from_attributes": True}


# --- Record Detail (GET /record/{id}) ---
class CoverImageInfo(BaseModel):
    url: str


class LifestorySummary(BaseModel):
    mood: str
    content: str


class EventItem(BaseModel):
    title: str
    timestamp: datetime
    description: str


class TimelineSummary(BaseModel):
    events: list[EventItem]


class RecordDetailResponse(BaseModel):
    id: uuid.UUID
    title: str
    subtitle: str | None = None
    googlePhotoUrl: str | None = None
    icloudUrl: str | None = None
    myboxUrl: str | None = None
    mediaList: list[MediaItem] = []
    coverImage: CoverImageInfo | None = None
    lifestory: LifestorySummary | None = None
    timeline: TimelineSummary | None = None
    createdAt: datetime
    updatedAt: datetime

    model_config = {"from_attributes": True}


# --- Lifestory ---
class LifestoryDetailResponse(BaseModel):
    mood: str
    qaList: list[QaItem]
    result: str


class CreateStorylinesRequest(BaseModel):
    qaList: list[QaItem]
    mood: str


class CreateStorylinesResponse(BaseModel):
    result: str


class SaveLifestoryRequest(BaseModel):
    qaList: list[QaItem]
    mood: str
    result: str


# --- Timeline ---
class SaveTimelineRequest(BaseModel):
    events: list[EventItem]


class TimelineResponse(BaseModel):
    events: list[EventItem]


# --- Cover Image ---
class CoverImageResponse(BaseModel):
    url: str


# --- Record List (GET /library) ---
class RecordListItem(BaseModel):
    id: uuid.UUID
    title: str
    subtitle: str | None = None
    coverImage: CoverImageInfo | None = None
    createdAt: datetime
    updatedAt: datetime
