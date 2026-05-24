"""add exhibition_type to records

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-05-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f3a4b5c6d7e8"
down_revision: Union[str, None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # exhibitiontype enum 생성
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'exhibitiontype') THEN "
        "CREATE TYPE exhibitiontype AS ENUM ('walk', 'memorial_tape'); "
        "END IF; "
        "END $$"
    )

    # exhibition_type 컬럼 추가 (기존 레코드는 모두 'walk')
    op.add_column(
        "records",
        sa.Column(
            "exhibition_type",
            sa.Enum("walk", "memorial_tape", name="exhibitiontype", create_type=False),
            nullable=False,
            server_default=sa.text("'walk'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("records", "exhibition_type")
    op.execute("DROP TYPE IF EXISTS exhibitiontype")
