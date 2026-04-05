"""add cover title settings columns

Revision ID: 24f58a1b2c5e
Revises: f4a5b6c7d8e9
Create Date: 2026-04-05 23:28:36.863558

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '24f58a1b2c5e'
down_revision: Union[str, None] = 'f4a5b6c7d8e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('records', sa.Column('cover_title_visible', sa.Boolean(), server_default=sa.text('true'), nullable=False))
    op.add_column('records', sa.Column('cover_title_position', sa.String(length=20), server_default=sa.text("'center-center'"), nullable=False))
    op.add_column('records', sa.Column('cover_title_font', sa.String(length=100), nullable=True))
    op.add_column('records', sa.Column('cover_title_color', sa.String(length=7), nullable=True))


def downgrade() -> None:
    op.drop_column('records', 'cover_title_color')
    op.drop_column('records', 'cover_title_font')
    op.drop_column('records', 'cover_title_position')
    op.drop_column('records', 'cover_title_visible')
