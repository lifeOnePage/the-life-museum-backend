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
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS credits INTEGER NOT NULL DEFAULT 0")

    # TxType enum 생성
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'txtype') THEN "
        "CREATE TYPE txtype AS ENUM "
        "('purchase', 'album_create', 'emoji_buy', 'refund', 'admin'); "
        "END IF; "
        "END $$"
    )

    # credit_transactions 테이블 생성
    op.execute("""
        CREATE TABLE IF NOT EXISTS credit_transactions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            tx_type txtype NOT NULL,
            amount INTEGER NOT NULL,
            balance_after INTEGER NOT NULL,
            description TEXT,
            reference_id VARCHAR(255),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_credit_transactions_user_id "
        "ON credit_transactions (user_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_credit_transactions_user_id")
    op.execute("DROP TABLE IF EXISTS credit_transactions")
    op.execute("DROP TYPE IF EXISTS txtype")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS credits")
