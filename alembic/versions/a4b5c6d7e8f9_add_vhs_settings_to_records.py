"""add vhs settings to records

Revision ID: a4b5c6d7e8f9
Revises: f3a4b5c6d7e8
Create Date: 2026-06-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a4b5c6d7e8f9"
down_revision: Union[str, None] = "f3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "records",
        sa.Column("vhs_filter", sa.String(20), nullable=True),
    )
    op.add_column(
        "records",
        sa.Column("vhs_transition", sa.String(20), nullable=True),
    )
    op.add_column(
        "records",
        sa.Column("vhs_photo_frame_index", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("records", "vhs_photo_frame_index")
    op.drop_column("records", "vhs_transition")
    op.drop_column("records", "vhs_filter")
