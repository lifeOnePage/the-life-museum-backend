"""add stickers to records

뒷면 스티커 목록 영속화 — [{id, assetId, src, x, y, rotation, scale}, ...]
(x/y는 0..1 정규화 좌표. id/assetId는 프론트 편집기 키로 재편집에 필요).
NULL = 스티커 없음 (기존 레코드 회귀 없음).

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-08-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b9c0d1e2f3a4'
down_revision: Union[str, None] = 'a8b9c0d1e2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'records',
        sa.Column('stickers', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('records', 'stickers')
