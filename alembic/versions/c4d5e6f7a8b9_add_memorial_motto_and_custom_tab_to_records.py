"""add memorial_motto, custom tab fields and poster settings to records

Revision ID: c4d5e6f7a8b9
Revises: a9b0c1d2e3f4
Create Date: 2026-09-17
"""

import sqlalchemy as sa
from alembic import op

revision = "c4d5e6f7a8b9"
down_revision = "a9b0c1d2e3f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 추모 앨범 모토 (부제목과 별개, 최대 25자)
    op.add_column(
        "records",
        sa.Column("memorial_motto", sa.String(length=50), nullable=True),
    )
    # 사용자 지정 탭 (on/off, 탭 이름, 열기 방식)
    op.add_column(
        "records",
        sa.Column(
            "custom_tab_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "records",
        sa.Column("custom_tab_label", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "records",
        sa.Column("custom_tab_mode", sa.String(length=10), nullable=True),
    )
    # 인트로 포스터 설정 (스타일 / 톤 / 화면 비율) — 프론트가 이미 PATCH로 보내던 값
    op.add_column(
        "records",
        sa.Column("memorial_poster_style", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "records",
        sa.Column("memorial_poster_tone", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "records",
        sa.Column("memorial_aspect_ratio", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("records", "memorial_aspect_ratio")
    op.drop_column("records", "memorial_poster_tone")
    op.drop_column("records", "memorial_poster_style")
    op.drop_column("records", "custom_tab_mode")
    op.drop_column("records", "custom_tab_label")
    op.drop_column("records", "custom_tab_enabled")
    op.drop_column("records", "memorial_motto")
