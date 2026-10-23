"""b10 share version ids

B10 멘토 공유: 공유 시점의 문항별 버전을 고정한다(part2_guide 4.40). 기존 행은 빈 배열.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-23 05:41:28.139906

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0012'
down_revision: Union[str, Sequence[str], None] = '0011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('shares', sa.Column('version_ids', postgresql.ARRAY(sa.Uuid()), server_default='{}', nullable=False))


def downgrade() -> None:
    op.drop_column('shares', 'version_ids')
