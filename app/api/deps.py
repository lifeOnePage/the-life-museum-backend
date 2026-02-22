from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.core.security import decode_token
from app.services.auth import AuthService
from app.models.user import User

security = HTTPBearer(auto_error=False)


async def _get_dev_user(db: AsyncSession) -> User | None:
    """DEV_AUTH_KEY가 설정되어 있을 때, DB의 첫 번째 유저를 반환"""
    result = await db.execute(select(User).limit(1))
    return result.scalar_one_or_none()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    x_dev_key: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
) -> User:
    # 개발 모드 우회: X-Dev-Key 헤더가 DEV_AUTH_KEY와 일치하면 첫 번째 유저 반환
    if x_dev_key and settings.DEV_AUTH_KEY and x_dev_key == settings.DEV_AUTH_KEY:
        user = await _get_dev_user(db)
        if user:
            return user

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    payload = decode_token(token)

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    auth_service = AuthService(db)
    user = await auth_service.get_user_by_id(user_id)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user",
        )

    return user


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(HTTPBearer(auto_error=False)),
    x_dev_key: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    # 개발 모드 우회
    if x_dev_key and settings.DEV_AUTH_KEY and x_dev_key == settings.DEV_AUTH_KEY:
        return await _get_dev_user(db)

    if credentials is None:
        return None

    try:
        token = credentials.credentials
        payload = decode_token(token)

        if payload is None or payload.get("type") != "access":
            return None

        user_id = payload.get("sub")
        if user_id is None:
            return None

        auth_service = AuthService(db)
        user = await auth_service.get_user_by_id(user_id)

        if user is None or not user.is_active:
            return None

        return user
    except Exception:
        return None
