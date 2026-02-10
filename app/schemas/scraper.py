from pydantic import BaseModel, HttpUrl
from enum import Enum


class MediaType(str, Enum):
    IMAGE = "image"
    VIDEO = "video"


class MediaItem(BaseModel):
    type: MediaType
    thumbnail_url: str
    original_url: str


class ScraperRequest(BaseModel):
    url: HttpUrl


class ScraperResponse(BaseModel):
    success: bool
    url: str
    provider: str | None = None
    media_count: int
    media: list[MediaItem]
    message: str | None = None
