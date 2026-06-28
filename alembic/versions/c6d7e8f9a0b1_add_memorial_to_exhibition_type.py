"""add memorial to exhibitiontype enum

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
Create Date: 2026-06-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c6d7e8f9a0b1"
down_revision: Union[str, None] = "b5c6d7e8f9a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 'memorial' 값을 exhibitiontype enum에 추가 (비파괴적, 값 추가만)
    op.execute("ALTER TYPE exhibitiontype ADD VALUE IF NOT EXISTS 'memorial'")


def downgrade() -> None:
    # PostgreSQL은 enum 값 단순 제거를 지원하지 않는다.
    # 안전한 비파괴 마이그레이션을 위해 downgrade는 no-op로 둔다.
    # (값 제거가 필요하면 enum 재생성 + 컬럼 재캐스팅이 필요)
    pass
