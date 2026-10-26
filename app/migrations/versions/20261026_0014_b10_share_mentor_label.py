"""b10 share mentor label

B10 후속: 작성자가 붙이는 멘토 별칭(1~20자, part2_guide 4.43). API는 필수로 받고,
DB 기본값 '멘토'는 기존 행과 API 밖에서 만든 행(테스트·배치)용.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-26 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0014'
down_revision: Union[str, Sequence[str], None] = '0013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('shares', sa.Column('mentor_label', sa.String(length=20), server_default='멘토', nullable=False))


def downgrade() -> None:
    op.drop_column('shares', 'mentor_label')
