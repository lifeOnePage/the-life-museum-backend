from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator

FlowerType = Literal["chrysanthemum", "lily", "carnation"]


class GuestbookEntryCreate(BaseModel):
    authorName: str
    flowerType: FlowerType
    message: str

    @field_validator("authorName")
    @classmethod
    def validate_author_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("이름을 입력해주세요")
        if len(v) > 10:
            raise ValueError("이름은 10자 이내여야 합니다")
        return v

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("추모의 한마디를 입력해주세요")
        if len(v) > 300:
            raise ValueError("추모의 한마디는 300자 이내여야 합니다")
        return v


class GuestbookEntryItem(BaseModel):
    id: uuid.UUID
    authorName: str
    flowerType: str
    message: str
    createdAt: datetime


class GuestbookListResponse(BaseModel):
    entries: list[GuestbookEntryItem]
    total: int


class GuestbookCreateResponse(BaseModel):
    entry: GuestbookEntryItem
    total: int
