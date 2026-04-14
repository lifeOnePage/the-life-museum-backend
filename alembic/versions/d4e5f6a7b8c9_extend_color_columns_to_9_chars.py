"""extend color columns to 9 chars and backfill alpha

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-14 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 7자리 → 9자리로 확장할 컬럼 목록
COLOR_COLUMNS = ['color', 'bg_color', 'key_color', 'cover_title_color', 'cover_title_bg_color']


def upgrade() -> None:
    # 1) 컬럼 길이 확장: VARCHAR(7) → VARCHAR(9)
    for col in COLOR_COLUMNS:
        op.alter_column(
            'records', col,
            type_=sa.String(9),
            existing_type=sa.String(7),
            existing_nullable=True,
        )

    # 2) 기존 7자리(#rrggbb) 값에 'ff' (불투명) 알파 추가
    for col in COLOR_COLUMNS:
        op.execute(
            sa.text(
                f"UPDATE records SET {col} = {col} || 'ff' "
                f"WHERE {col} IS NOT NULL AND length({col}) = 7"
            )
        )


def downgrade() -> None:
    # 알파 제거: 9자리 → 앞 7자리만 유지
    for col in COLOR_COLUMNS:
        op.execute(
            sa.text(
                f"UPDATE records SET {col} = left({col}, 7) "
                f"WHERE {col} IS NOT NULL AND length({col}) = 9"
            )
        )

    for col in COLOR_COLUMNS:
        op.alter_column(
            'records', col,
            type_=sa.String(7),
            existing_type=sa.String(9),
            existing_nullable=True,
        )
