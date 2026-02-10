from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, PhoneVerification
from app.schemas.user import UserCreate
from app.core.security import get_password_hash, verify_password
from app.core.exceptions import BadRequestException, NotFoundException, ConflictException


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_user_by_email(self, email: str) -> User | None:
        result = await self.db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_user_by_phone(self, phone: str) -> User | None:
        result = await self.db.execute(select(User).where(User.phone == phone))
        return result.scalar_one_or_none()

    async def get_user_by_id(self, user_id: int) -> User | None:
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def create_user(self, user_data: UserCreate) -> User:
        if user_data.email:
            existing = await self.get_user_by_email(user_data.email)
            if existing:
                raise ConflictException("Email already registered")

        if user_data.phone:
            existing = await self.get_user_by_phone(user_data.phone)
            if existing:
                raise ConflictException("Phone already registered")

        hashed_password = None
        if user_data.password:
            hashed_password = get_password_hash(user_data.password)

        user = User(
            email=user_data.email,
            phone=user_data.phone,
            hashed_password=hashed_password,
            name=user_data.name,
        )
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def authenticate(self, email: str | None, phone: str | None, password: str) -> User | None:
        user = None
        if email:
            user = await self.get_user_by_email(email)
        elif phone:
            user = await self.get_user_by_phone(phone)

        if not user or not user.hashed_password:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user

    async def create_phone_verification(self, phone: str, code: str) -> PhoneVerification:
        # Delete existing verifications for this phone
        existing = await self.db.execute(
            select(PhoneVerification).where(PhoneVerification.phone == phone)
        )
        for v in existing.scalars().all():
            await self.db.delete(v)

        verification = PhoneVerification(
            phone=phone,
            code=code,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        self.db.add(verification)
        await self.db.commit()
        await self.db.refresh(verification)
        return verification

    async def verify_phone_code(self, phone: str, code: str) -> bool:
        result = await self.db.execute(
            select(PhoneVerification).where(
                PhoneVerification.phone == phone,
                PhoneVerification.is_verified == False,
            )
        )
        verification = result.scalar_one_or_none()

        if not verification:
            raise NotFoundException("Verification not found")

        if verification.expires_at < datetime.now(timezone.utc):
            raise BadRequestException("Verification code expired")

        if verification.attempts >= 5:
            raise BadRequestException("Too many attempts")

        if verification.code != code:
            verification.attempts += 1
            await self.db.commit()
            raise BadRequestException("Invalid verification code")

        verification.is_verified = True
        await self.db.commit()
        return True
