from pydantic import BaseModel, HttpUrl
from enum import Enum


class MediaType(str, Enum):
    IMAGE = "image"
    VIDEO = "video"


class MediaItem(BaseModel):
    type: MediaType
    thumbnail_url: str
    original_url: str
    # 앨범 커버(og:image)와 동일한 항목 여부 — 공유 페이지 헤더가 커버라서
    # 스크랩 목록의 첫 항목이 항상 커버가 되는 문제를 프론트에서 구분하기 위함
    is_cover: bool = False


class ScraperRequest(BaseModel):
    url: HttpUrl


class ScraperResponse(BaseModel):
    success: bool
    url: str
    provider: str | None = None
    media_count: int
    media: list[MediaItem]
    message: str | None = None
