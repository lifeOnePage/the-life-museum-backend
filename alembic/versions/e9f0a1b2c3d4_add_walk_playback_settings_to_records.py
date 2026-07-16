"""add walk(time travel) playback settings to records

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
Create Date: 2026-07-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e9f0a1b2c3d4"
down_revision: Union[str, None] = "d8e9f0a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 카메라 속도(5~240), 비디오 짧게 보기 on/off, 짧게 볼 때 최대 재생 시간(초)
    op.add_column(
        "records",
        sa.Column("walk_camera_speed", sa.Integer(), nullable=True),
    )
    op.add_column(
        "records",
        sa.Column("walk_video_preview", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "records",
        sa.Column("walk_video_max_duration", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("records", "walk_video_max_duration")
    op.drop_column("records", "walk_video_preview")
    op.drop_column("records", "walk_camera_speed")
