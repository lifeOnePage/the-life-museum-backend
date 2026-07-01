"""add free_trial_used to users

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-07-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd2e3f4a5b6c7'
down_revision: Union[str, None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column(
            'free_trial_used',
            sa.Boolean(),
            server_default=sa.text('false'),
            nullable=False,
        ),
    )
    # 백필: 이미 앨범을 1개 이상 소유한 유저는 무료 혜택을 이미 사용한 것으로 간주.
    # (기존 로직상 앨범이 있으면 어차피 무료로 안 나갔으므로 동작 동일하게 유지)
    op.execute(
        """
        UPDATE users
        SET free_trial_used = true
        WHERE id IN (SELECT DISTINCT creator_id FROM records)
        """
    )


def downgrade() -> None:
    op.drop_column('users', 'free_trial_used')
