"""c15 applications drop rejected, add position

① 상태 '불합격(rejected)' 삭제 → 4단계(사용자 결정 2026-10-28, docs/C15.md). 기존 rejected 행은 **삭제**
   (사용자 선택). spec·tasks C15는 5단계 — Plan.md "근거 문서 갱신 필요 사항"에 기록.
② 칸반 열 안 순서 `position`(작을수록 위). 기존 행은 (소유자, 상태)별 최근 수정순으로 0,1,2… 채운다.

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-28 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0019'
down_revision: Union[str, Sequence[str], None] = '0018'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FOUR = "'applied', 'document_passed', 'interview', 'final'"
_FIVE = _FOUR + ", 'rejected'"


def upgrade() -> None:
    op.execute("DELETE FROM applications WHERE status = 'rejected'")
    op.drop_constraint(op.f('ck_applications_status'), 'applications', type_='check')
    op.create_check_constraint(op.f('ck_applications_status'), 'applications', f"status IN ({_FOUR})")

    op.add_column('applications', sa.Column('position', sa.Integer(), server_default='0', nullable=False))
    op.execute(
        """
        UPDATE applications a SET position = o.rn
        FROM (
            SELECT id, row_number() OVER (PARTITION BY owner_id, status ORDER BY updated_at DESC) - 1 AS rn
            FROM applications
        ) o
        WHERE a.id = o.id
        """
    )


def downgrade() -> None:
    op.drop_column('applications', 'position')
    op.drop_constraint(op.f('ck_applications_status'), 'applications', type_='check')
    op.create_check_constraint(op.f('ck_applications_status'), 'applications', f"status IN ({_FIVE})")
