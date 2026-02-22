"""add email_verifications table

Revision ID: b1c2d3e4f5a6
Revises: a3b1c2d4e5f6
Create Date: 2026-02-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, None] = 'a3b1c2d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'email_verifications',
        sa.Column(
            'id',
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text('gen_random_uuid()'),
            nullable=False,
        ),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('code', sa.String(length=6), nullable=False),
        sa.Column('is_verified', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index('ix_email_verifications_email', 'email_verifications', ['email'])


def downgrade() -> None:
    op.drop_index('ix_email_verifications_email', table_name='email_verifications')
    op.drop_table('email_verifications')
