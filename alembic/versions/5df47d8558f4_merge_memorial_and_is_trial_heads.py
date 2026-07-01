"""merge memorial and is_trial heads

Revision ID: 5df47d8558f4
Revises: c6d7e8f9a0b1, c1d2e3f4a5b6
Create Date: 2026-07-01 12:04:25.556113

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5df47d8558f4'
down_revision: Union[str, None] = ('c6d7e8f9a0b1', 'c1d2e3f4a5b6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
