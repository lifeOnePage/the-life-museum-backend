import uuid
from datetime import datetime
from pydantic import BaseModel, EmailStr


class UserBase(BaseModel):
    email: EmailStr | None = None
    phone: str | None = None
    name: str | None = None


class UserCreate(UserBase):
    password: str | None = None


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    phone: str | None = None
    name: str | None = None
    profile_image: str | None = None


class UserResponse(UserBase):
    id: uuid.UUID
    profile_image: str | None = None
    is_active: bool
    is_verified: bool
    credits: int = 0
    free_trial_used: bool = False
    created_at: datetime

    class Config:
        from_attributes = True
