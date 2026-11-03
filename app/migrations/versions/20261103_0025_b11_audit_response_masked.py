"""b11 audit response masked

AI 사용 기록(B11)에 답변 칸 추가(part2_guide 4.68·4.74). A8이 사용자에게 돌려준 답변을
복원 전(PII 토큰) 상태로 넘기고 마스킹을 한 번 더 거쳐 저장한다. 차단된 요청은 NULL.
수정 방지 트리거(0009)는 행 전체를 비교하므로 새 칸도 그대로 보호된다.

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-03 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0025'
down_revision: Union[str, Sequence[str], None] = '0024'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('audit_logs', sa.Column('response_masked', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('audit_logs', 'response_masked')
