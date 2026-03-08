"""add user_record_associations and remove records.user_id

Revision ID: d1e2f3a4b5c6
Revises: c2d3e4f5a6b7
Create Date: 2026-03-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, None] = 'c2d3e4f5a6b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. user_record_associations 테이블 생성
    op.create_table(
        'user_record_associations',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('record_id', sa.UUID(), nullable=False),
        sa.Column('role', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.CheckConstraint("role IN ('owner', 'shared')", name='ck_ura_role'),
        sa.ForeignKeyConstraint(['record_id'], ['records.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'record_id', name='uq_ura_user_record'),
    )
    op.create_index('ix_ura_user_id', 'user_record_associations', ['user_id'])
    op.create_index('ix_ura_record_id', 'user_record_associations', ['record_id'])

    # 2. 기존 데이터 이전: records.user_id → user_record_associations(role='owner')
    op.execute(
        """
        INSERT INTO user_record_associations (id, user_id, record_id, role, created_at)
        SELECT gen_random_uuid(), user_id, id, 'owner', created_at
        FROM records
        WHERE user_id IS NOT NULL
        """
    )

    # 3. records.user_id FK 제약조건, 인덱스, 컬럼 삭제
    op.drop_constraint('records_user_id_fkey', 'records', type_='foreignkey')
    op.drop_index('ix_records_user_id', table_name='records')
    op.drop_column('records', 'user_id')


def downgrade() -> None:
    # 1. records.user_id 컬럼 복원 (nullable=True 로 먼저 추가)
    op.add_column(
        'records',
        sa.Column('user_id', sa.UUID(), nullable=True),
    )

    # 2. owner 연관에서 user_id 복원
    op.execute(
        """
        UPDATE records r
        SET user_id = ura.user_id
        FROM user_record_associations ura
        WHERE ura.record_id = r.id AND ura.role = 'owner'
        """
    )

    # 3. NOT NULL 적용
    op.alter_column('records', 'user_id', nullable=False)

    # 4. FK 제약조건 및 인덱스 복원
    op.create_foreign_key(
        'records_user_id_fkey', 'records', 'users', ['user_id'], ['id'], ondelete='CASCADE'
    )
    op.create_index('ix_records_user_id', 'records', ['user_id'])

    # 5. user_record_associations 테이블 삭제
    op.drop_index('ix_ura_record_id', table_name='user_record_associations')
    op.drop_index('ix_ura_user_id', table_name='user_record_associations')
    op.drop_table('user_record_associations')
