"""d16 blocked sessions

D16 차단 세션 목록(blocked_sessions). 자동 차단(카나리·탈취 임계치)과 운영자 수동 차단.
모델 app/models/blocked_session.py. B 취합 규칙(tasks.md "모델 추가는 B가 취합")에 따라 [B 리뷰 요청].

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-03 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0025'
down_revision: Union[str, Sequence[str], None] = '0024'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('blocked_sessions',
    sa.Column('session_id', sa.String(length=128), nullable=False),
    sa.Column('user_id', sa.String(length=128), nullable=False),
    sa.Column('reason', sa.String(length=50), nullable=False),
    sa.Column('rule_id', sa.String(length=50), nullable=True),
    sa.Column('note', sa.String(length=300), nullable=True),
    sa.Column('blocked_by', sa.String(length=128), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('released_by', sa.String(length=128), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('session_id', name=op.f('pk_blocked_sessions'))
    )
    op.create_index('ix_blocked_sessions_user_created', 'blocked_sessions', ['user_id', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_blocked_sessions_user_created', table_name='blocked_sessions')
    op.drop_table('blocked_sessions')
