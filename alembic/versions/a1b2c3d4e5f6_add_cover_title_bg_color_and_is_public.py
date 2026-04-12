"""add cover_title_bg_color and is_public to records

Revision ID: a1b2c3d4e5f6
Revises: 24f58a1b2c5e
Create Date: 2026-04-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '24f58a1b2c5e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('records', sa.Column('cover_title_bg_color', sa.String(length=7), nullable=True))
    op.add_column('records', sa.Column('is_public', sa.Boolean(), server_default=sa.text('false'), nullable=False))


def downgrade() -> None:
    op.drop_column('records', 'is_public')
    op.drop_column('records', 'cover_title_bg_color')
