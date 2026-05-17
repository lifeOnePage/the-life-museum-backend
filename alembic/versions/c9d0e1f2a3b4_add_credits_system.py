"""add credits system

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-05-18 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # users 테이블에 credits 컬럼 추가
    op.add_column(
        "users",
        sa.Column("credits", sa.Integer(), server_default="0", nullable=False),
    )

    # TxType enum 생성
    txtype_enum = sa.Enum(
        "purchase", "album_create", "emoji_buy", "refund", "admin",
        name="txtype",
    )
    txtype_enum.create(op.get_bind(), checkfirst=True)

    # credit_transactions 테이블 생성
    op.create_table(
        "credit_transactions",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "tx_type",
            sa.Enum(
                "purchase", "album_create", "emoji_buy", "refund", "admin",
                name="txtype",
            ),
            nullable=False,
        ),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("reference_id", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_credit_transactions_user_id"),
        "credit_transactions",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_credit_transactions_user_id"),
        table_name="credit_transactions",
    )
    op.drop_table("credit_transactions")

    # TxType enum 삭제
    sa.Enum(name="txtype").drop(op.get_bind(), checkfirst=True)

    op.drop_column("users", "credits")
