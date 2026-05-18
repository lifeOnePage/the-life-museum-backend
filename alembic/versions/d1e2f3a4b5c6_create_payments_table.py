"""create payments table

Revision ID: d1e2f3a4b5c6
Revises: c9d0e1f2a3b4
Create Date: 2026-05-18 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PaymentStatus enum 생성
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'paymentstatus') THEN "
        "CREATE TYPE paymentstatus AS ENUM ('confirmed', 'failed'); "
        "END IF; "
        "END $$"
    )

    # payments 테이블 생성
    op.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            gateway VARCHAR(20) NOT NULL,
            gateway_tx_id VARCHAR(255) NOT NULL,
            package VARCHAR(50),
            amount INTEGER,
            currency VARCHAR(10),
            status paymentstatus NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_payments_gateway_tx_id "
        "ON payments (gateway_tx_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_payments_user_id "
        "ON payments (user_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_payments_user_id")
    op.execute("DROP INDEX IF EXISTS ix_payments_gateway_tx_id")
    op.execute("DROP TABLE IF EXISTS payments")
    op.execute("DROP TYPE IF EXISTS paymentstatus")
