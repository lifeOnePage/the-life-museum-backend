"""add discount coupon fields

쿠폰을 크레딧/할인 2타입으로 확장:
- coupon_type: 'credit' | 'discount'
- 할인 쿠폰: discount_percent(%) + max_discount_krw(상한, 원화 기준)
- 할인 쿠폰은 redeem 시 즉시 소모되지 않고 유저 보관함에 등록(claim)된 뒤
  결제에서 소모되므로 claimed_* 필드 추가

Revision ID: a8b9c0d1e2f3
Revises: e9f0a1b2c3d4
Create Date: 2026-07-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, None] = "e9f0a1b2c3d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "coupons",
        sa.Column(
            "coupon_type",
            sa.String(20),
            server_default="credit",
            nullable=False,
        ),
    )
    op.add_column(
        "coupons", sa.Column("discount_percent", sa.Integer(), nullable=True)
    )
    op.add_column(
        "coupons", sa.Column("max_discount_krw", sa.Integer(), nullable=True)
    )
    op.add_column(
        "coupons",
        sa.Column(
            "claimed_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "coupons",
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_coupons_claimed_by_user_id", "coupons", ["claimed_by_user_id"]
    )
    # 할인 쿠폰은 credit_amount가 없으므로 nullable로 완화
    op.alter_column("coupons", "credit_amount", nullable=True)


def downgrade() -> None:
    op.alter_column("coupons", "credit_amount", nullable=False)
    op.drop_index("ix_coupons_claimed_by_user_id", table_name="coupons")
    op.drop_column("coupons", "claimed_at")
    op.drop_column("coupons", "claimed_by_user_id")
    op.drop_column("coupons", "max_discount_krw")
    op.drop_column("coupons", "discount_percent")
    op.drop_column("coupons", "coupon_type")
