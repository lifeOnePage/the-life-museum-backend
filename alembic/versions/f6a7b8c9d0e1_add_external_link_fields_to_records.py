"""add external_link_title and external_link_url to records

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-04-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('records', sa.Column('external_link_title', sa.String(255), nullable=True))
    op.add_column('records', sa.Column('external_link_url', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('records', 'external_link_url')
    op.drop_column('records', 'external_link_title')
