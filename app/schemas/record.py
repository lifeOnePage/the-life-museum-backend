from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, AfterValidator

from app.schemas.scraper import MediaItem

# 무료 체험 앨범 유효 기간 (생성일 기준)
TRIAL_DAYS = 30

# 추모(memorial) 앨범이 보존하는 미디어 최대 개수.
# 프론트 app/lib/constants.js의 MEMORIAL_MAX_MEDIA와 반드시 동일 값 유지.
MEMORIAL_MAX_MEDIA = 36


def trial_fields(is_trial: bool, created_at: datetime) -> dict:
    """체험 앨범 응답 필드 계산 (isTrial / trialExpiresAt / isExpired)."""
    if not is_trial:
        return {"isTrial": False, "trialExpiresAt": None, "isExpired": False}
    expires_at = created_at + timedelta(days=TRIAL_DAYS)
    now = datetime.now(timezone.utc)
    # created_at이 naive일 경우 대비
    if expires_at.tzinfo is None:
        now = now.replace(tzinfo=None)
    return {
        "isTrial": True,
        "trialExpiresAt": expires_at,
        "isExpired": now > expires_at,
    }


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
    googleDriveUrl: str | None = None
    icloudUrl: str | None = None
    myboxUrl: str | None = None
    # "memorial"이면 소스 URL 없이 생성 후 memorial-media 인제스트로 미디어 등록
    recordType: str | None = None


# --- Memorial 미디어 인제스트 ---
class MemorialMediaItemIn(BaseModel):
    url: str
    thumbnailUrl: str | None = None
    type: Literal["image", "video"]
    mimeType: str | None = None


class MemorialMediaIngestRequest(BaseModel):
    source: Literal["google_picker", "conversion", "upload"]
    # google_picker 전용 — baseUrl 다운로드에 Authorization 헤더로 사용
    accessToken: str | None = None
    items: list[MemorialMediaItemIn]


class ConvertToMemorialRequest(BaseModel):
    title: str | None = None
    subTitle: str | None = None
    items: list[MemorialMediaItemIn]


class RecordUpdate(BaseModel):
    title: str | None = None
    subTitle: str | None = None
    googlePhotoUrl: str | None = None
    googleDriveUrl: str | None = None
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
    guestbookEnabled: bool | None = None
    bgmId: int | None = None
    bgmUrl: str | None = None
    externalLinkTitle: str | None = None
    externalLinkUrl: str | None = None
    backCoverImageUrl: str | None = None
    stickers: list | None = None
    recordType: str | None = None
    vhsFilter: str | None = None
    vhsTransition: str | None = None
    vhsPhotoFrameIndex: int | None = None
    vhsImageDuration: int | None = None
    vhsVideoMode: int | None = None
    walkCameraSpeed: int | None = None
    walkVideoPreview: bool | None = None
    walkVideoMaxDuration: int | None = None


class PublicUpdateRequest(BaseModel):
    isPublic: bool


class RecordResponse(BaseModel):
    id: uuid.UUID
    title: str
    subtitle: str | None = None
    googlePhotoUrl: str | None = None
    googleDriveUrl: str | None = None
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
    stickers: list | None = None
    recordType: str = "exhibit"
    vhsFilter: str | None = None
    vhsTransition: str | None = None
    vhsPhotoFrameIndex: int | None = None
    vhsImageDuration: int | None = None
    vhsVideoMode: int | None = None
    walkCameraSpeed: int | None = None
    walkVideoPreview: bool | None = None
    walkVideoMaxDuration: int | None = None
    coverImage: CoverImageInfo | None = None
    isTrial: bool = False
    trialExpiresAt: datetime | None = None
    isExpired: bool = False
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
    # memorial 전용: 영속 미디어 인제스트 상태 (processing | ready). 그 외 None.
    # 감상 페이지가 "준비 중" 인터스티셜을 띄우고 폴링하는 데 사용.
    mediaStatus: str | None = None
    googlePhotoUrl: str | None = None
    googleDriveUrl: str | None = None
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
    guestbookEnabled: bool = True
    bgmId: int | None = None
    bgmUrl: str | None = None
    externalLinkTitle: str | None = None
    externalLinkUrl: str | None = None
    backCoverImageUrl: str | None = None
    stickers: list | None = None
    recordType: str = "exhibit"
    vhsFilter: str | None = None
    vhsTransition: str | None = None
    vhsPhotoFrameIndex: int | None = None
    vhsImageDuration: int | None = None
    vhsVideoMode: int | None = None
    walkCameraSpeed: int | None = None
    walkVideoPreview: bool | None = None
    walkVideoMaxDuration: int | None = None
    coverGenCount: int = 0
    storyGenCount: int = 0
    coverImage: CoverImageInfo | None = None
    lifestory: LifestorySummary | None = None
    timeline: TimelineSummary | None = None
    isTrial: bool = False
    trialExpiresAt: datetime | None = None
    isExpired: bool = False
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
    stickers: list | None = None
    recordType: str = "exhibit"
    vhsFilter: str | None = None
    vhsTransition: str | None = None
    vhsPhotoFrameIndex: int | None = None
    vhsImageDuration: int | None = None
    vhsVideoMode: int | None = None
    walkCameraSpeed: int | None = None
    walkVideoPreview: bool | None = None
    walkVideoMaxDuration: int | None = None
    lifestory: LifestorySummary | None = None
    timeline: TimelineSummary | None = None
    role: Literal["owner", "shared"] = "owner"
    isTrial: bool = False
    trialExpiresAt: datetime | None = None
    isExpired: bool = False
    createdAt: datetime
    updatedAt: datetime


# --- Share ---
class ShareRecordRequest(BaseModel):
    url: str  # walk/{id} URL (전체 URL 또는 경로 포함)
