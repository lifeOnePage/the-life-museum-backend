"""merge free_trial_used and is_trial/memorial heads

Revision ID: 5bb336431dff
Revises: 5df47d8558f4, d2e3f4a5b6c7
Create Date: 2026-07-02 12:18:22.154723

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5bb336431dff'
down_revision: Union[str, None] = ('5df47d8558f4', 'd2e3f4a5b6c7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
