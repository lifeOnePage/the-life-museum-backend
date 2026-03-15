from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    future=True,
    # Neon 무료 티어 최대 동시 연결 = 5 → pool_size를 낮게 유지
    pool_size=3,
    max_overflow=2,  # 최대 5개 이내로 제한
    # 연결 대기 최대 10초 (초과 시 즉시 에러 → 오래 매달리지 않음)
    pool_timeout=10,
    # asyncpg 연결 시도 자체의 타임아웃 (CancelledError 방지)
    connect_args={"timeout": 20},
    # Neon PgBouncer 유휴 연결 끊김 대응
    pool_pre_ping=True,
    pool_recycle=240,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
