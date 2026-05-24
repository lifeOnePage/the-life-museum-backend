from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, AfterValidator

from app.schemas.scraper import MediaItem


def validate_hex_color(v: str | None) -> str | None:
    if v is None:
        return v
    if not re.fullmatch(r"#[0-9a-fA-F]{8}", v):
        raise ValueError("Invalid hex color. Must be # followed by 8 hex digits, e.g. #ff00aa55")
    return v.lower()


HexColor = Annotated[str | None, AfterValidator(validate_hex_color)]


# --- QA ---
class QaItem(BaseModel):
    question: str
    answer: str


# --- Record ---
class RecordCreate(BaseModel):
    title: str | None = None
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
    color: HexColor = None
    bgColor: HexColor = None
    keyColor: HexColor = None
    theme: str | None = None
    exhibitionType: str | None = None
    coverTitleVisible: bool | None = None
    coverTitlePosition: str | None = None
    coverTitleFont: str | None = None
    coverTitleColor: HexColor = None
    coverTitleBgColor: HexColor = None
    isPublic: bool | None = None
    bgmId: int | None = None
    bgmUrl: str | None = None
    externalLinkTitle: str | None = None
    externalLinkUrl: str | None = None
    backCoverImageUrl: str | None = None


class PublicUpdateRequest(BaseModel):
    isPublic: bool


class RecordResponse(BaseModel):
    id: uuid.UUID
    title: str
    subtitle: str | None = None
    googlePhotoUrl: str | None = None
    icloudUrl: str | None = None
    myboxUrl: str | None = None
    color: str | None = None
    bgColor: str | None = None
    keyColor: str | None = None
    theme: str | None = None
    exhibitionType: str = "walk"
    coverTitleVisible: bool = True
    coverTitlePosition: str = "center-center"
    coverTitleFont: str | None = None
    coverTitleColor: str | None = None
    coverTitleBgColor: str | None = None
    isPublic: bool = False
    bgmId: int | None = None
    bgmUrl: str | None = None
    externalLinkTitle: str | None = None
    externalLinkUrl: str | None = None
    backCoverImageUrl: str | None = None
    coverImage: CoverImageInfo | None = None
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
    timestamp: str
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
    color: str | None = None
    bgColor: str | None = None
    keyColor: str | None = None
    theme: str | None = None
    exhibitionType: str = "walk"
    coverTitleVisible: bool = True
    coverTitlePosition: str = "center-center"
    coverTitleFont: str | None = None
    coverTitleColor: str | None = None
    coverTitleBgColor: str | None = None
    isPublic: bool = False
    bgmId: int | None = None
    bgmUrl: str | None = None
    externalLinkTitle: str | None = None
    externalLinkUrl: str | None = None
    backCoverImageUrl: str | None = None
    coverGenCount: int = 0
    storyGenCount: int = 0
    coverImage: CoverImageInfo | None = None
    lifestory: LifestorySummary | None = None
    timeline: TimelineSummary | None = None
    createdAt: datetime
    updatedAt: datetime

    model_config = {"from_attributes": True}


class RecordMediaResponse(BaseModel):
    mediaList: list[MediaItem] = []


# --- Lifestory ---
class LifestoryDetailResponse(BaseModel):
    mood: str
    qaList: list[QaItem]
    result: str


class CreateStorylinesRequest(BaseModel):
    prompt: str
    albumTitle: str | None = None
    albumSubtitle: str | None = None


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


class CoverGenerateResponse(BaseModel):
    videos: list[str]  # R2 URLs (up to 3; partial failure allowed)


class CoverGenerateImageResponse(BaseModel):
    images: list[str]  # R2 URLs
    remainingGenerations: int


class CoverUrlRequest(BaseModel):
    url: str  # Already-uploaded R2 URL to save to DB


# --- Record List (GET /library) ---
class RecordListItem(BaseModel):
    id: uuid.UUID
    title: str
    subtitle: str | None = None
    coverImage: CoverImageInfo | None = None
    bgColor: str | None = None
    color: str | None = None
    keyColor: str | None = None
    theme: str | None = None
    exhibitionType: str = "walk"
    coverTitleVisible: bool = True
    coverTitlePosition: str = "center-center"
    coverTitleFont: str | None = None
    coverTitleColor: str | None = None
    coverTitleBgColor: str | None = None
    isPublic: bool = False
    bgmId: int | None = None
    bgmUrl: str | None = None
    externalLinkTitle: str | None = None
    externalLinkUrl: str | None = None
    backCoverImageUrl: str | None = None
    lifestory: LifestorySummary | None = None
    timeline: TimelineSummary | None = None
    role: Literal["owner", "shared"] = "owner"
    createdAt: datetime
    updatedAt: datetime


# --- Share ---
class ShareRecordRequest(BaseModel):
    url: str  # walk/{id} URL (전체 URL 또는 경로 포함)
