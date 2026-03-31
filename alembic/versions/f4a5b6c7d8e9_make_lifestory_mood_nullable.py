"""make lifestory mood and event description nullable

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-03-30 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f4a5b6c7d8e9'
down_revision: Union[str, None] = 'e3f4a5b6c7d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'lifestories',
        'mood',
        existing_type=sa.String(length=100),
        nullable=True,
    )
    op.alter_column(
        'events',
        'description',
        existing_type=sa.Text(),
        nullable=True,
    )


def downgrade() -> None:
    op.execute("UPDATE lifestories SET mood = '' WHERE mood IS NULL")
    op.alter_column(
        'lifestories',
        'mood',
        existing_type=sa.String(length=100),
        nullable=False,
    )
    op.execute("UPDATE events SET description = '' WHERE description IS NULL")
    op.alter_column(
        'events',
        'description',
        existing_type=sa.Text(),
        nullable=False,
    )
