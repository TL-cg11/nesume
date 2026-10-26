"""b17 share comments

B17 멘토 문단별 코멘트(part2_guide 4.47). 작성자 자소서에 딸린 개인 등급 데이터.
공유·작성자 계정 삭제 시 CASCADE. 대응표(vault_id)는 B20 물리 삭제에서 함께 정리한다.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-26 02:38:35.720794

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0015'
down_revision: Union[str, Sequence[str], None] = '0014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('share_comments',
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('share_id', sa.Uuid(), nullable=False),
    sa.Column('owner_id', sa.String(length=128), nullable=False),
    sa.Column('version_id', sa.Uuid(), nullable=False),
    sa.Column('paragraph_index', sa.Integer(), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('vault_id', sa.String(length=64), nullable=True),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('grade', sa.String(length=20), server_default='personal', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("grade IN ('public', 'internal', 'personal', 'sensitive', 'confidential')", name=op.f('ck_share_comments_grade')),
    sa.CheckConstraint('paragraph_index >= 0', name=op.f('ck_share_comments_paragraph_index_nonneg')),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_share_comments_owner_id_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['share_id'], ['shares.id'], name=op.f('fk_share_comments_share_id_shares'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['vault_id'], ['pii_vaults.id'], name=op.f('fk_share_comments_vault_id_pii_vaults')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_share_comments'))
    )
    op.create_index(op.f('ix_share_comments_owner_id'), 'share_comments', ['owner_id'], unique=False)
    op.create_index(op.f('ix_share_comments_share_id'), 'share_comments', ['share_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_share_comments_share_id'), table_name='share_comments')
    op.drop_index(op.f('ix_share_comments_owner_id'), table_name='share_comments')
    op.drop_table('share_comments')
