"""add vhs playback settings (image duration, video mode) to records

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-07-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d8e9f0a1b2c3"
down_revision: Union[str, None] = "c7d8e9f0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 사진 표시 시간(초), 영상 재생 방식(0=전체 재생, N=짧게 N초)
    op.add_column(
        "records",
        sa.Column("vhs_image_duration", sa.Integer(), nullable=True),
    )
    op.add_column(
        "records",
        sa.Column("vhs_video_mode", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("records", "vhs_video_mode")
    op.drop_column("records", "vhs_image_duration")
