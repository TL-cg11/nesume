"""c7 rate limit counters

C7 레이트리밋 카운터(rate_limit_counters) 취합(B, tasks.md "모델 추가는 B가 취합").

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-27 01:52:15.264768

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0016'
down_revision: Union[str, Sequence[str], None] = '0015'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('rate_limit_counters',
    sa.Column('key', sa.String(length=200), nullable=False),
    sa.Column('window_start', sa.Float(), nullable=False),
    sa.Column('count', sa.BigInteger(), server_default='0', nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('key', name=op.f('pk_rate_limit_counters'))
    )


def downgrade() -> None:
    op.drop_table('rate_limit_counters')
