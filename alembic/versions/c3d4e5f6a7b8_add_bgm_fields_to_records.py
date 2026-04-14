"""add bgm_id and bgm_url to records

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'records',
        sa.Column('bgm_id', sa.Integer(), nullable=True),
    )
    op.add_column(
        'records',
        sa.Column('bgm_url', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('records', 'bgm_url')
    op.drop_column('records', 'bgm_id')
