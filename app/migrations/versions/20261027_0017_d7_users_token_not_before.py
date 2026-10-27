"""d7 users token not before

D7 토큰 무효화 기준 시각(users.token_not_before). 이 시각 이전에 발급된 액세스 토큰은 401(D7 iat 비교).
D6 역할 변경 API가 갱신한다. NULL이면 검사하지 않는다(part2_guide 4.51).

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-27 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0017'
down_revision: Union[str, Sequence[str], None] = '0016'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('token_not_before', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'token_not_before')
