"""extend cover_title_bg_color to varchar(9)

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-04-14 02:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'records', 'cover_title_bg_color',
        type_=sa.String(9),
        existing_type=sa.String(7),
        existing_nullable=True,
    )

    op.execute(
        sa.text(
            "UPDATE records SET cover_title_bg_color = cover_title_bg_color || 'ff' "
            "WHERE cover_title_bg_color IS NOT NULL AND length(cover_title_bg_color) = 7"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE records SET cover_title_bg_color = left(cover_title_bg_color, 7) "
            "WHERE cover_title_bg_color IS NOT NULL AND length(cover_title_bg_color) = 9"
        )
    )

    op.alter_column(
        'records', 'cover_title_bg_color',
        type_=sa.String(7),
        existing_type=sa.String(9),
        existing_nullable=True,
    )
