"""add color fields to records

Revision ID: a3b1c2d4e5f6
Revises: 77cf1a7999bd
Create Date: 2026-02-17 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a3b1c2d4e5f6'
down_revision: Union[str, None] = '77cf1a7999bd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('records', sa.Column('color', sa.String(length=7), nullable=True))
    op.add_column('records', sa.Column('bg_color', sa.String(length=7), nullable=True))
    op.add_column('records', sa.Column('key_color', sa.String(length=7), nullable=True))


def downgrade() -> None:
    op.drop_column('records', 'key_color')
    op.drop_column('records', 'bg_color')
    op.drop_column('records', 'color')
