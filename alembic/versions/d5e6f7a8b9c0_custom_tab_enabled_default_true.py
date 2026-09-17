"""custom_tab_enabled 기본값 true — 외부 링크가 있으면 하단 탭에 기본 노출

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-09-17
"""

import sqlalchemy as sa
from alembic import op

revision = "d5e6f7a8b9c0"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 새 레코드 기본값 on
    op.alter_column(
        "records",
        "custom_tab_enabled",
        existing_type=sa.Boolean(),
        server_default=sa.text("true"),
        existing_nullable=False,
    )
    # 기존 레코드도 on 으로 — 이 컬럼은 같은 날(c4d5e6f7a8b9) 생겼고 아직 편집 UI로
    # 끈 사용자가 없으므로 일괄 전환해도 의도와 어긋나지 않는다
    op.execute("UPDATE records SET custom_tab_enabled = true")


def downgrade() -> None:
    op.alter_column(
        "records",
        "custom_tab_enabled",
        existing_type=sa.Boolean(),
        server_default=sa.text("false"),
        existing_nullable=False,
    )
