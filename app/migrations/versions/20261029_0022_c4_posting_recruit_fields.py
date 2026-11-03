"""c4 job_postings.recruit_fields (모집분야별 내용)

공채속보 공고 하나에 모집분야가 여럿이면 지금은 한 행에 합쳐져 역량 갭·추천이 분야를 섞는다.
분야 목록을 JSONB로 따로 둔다(공고 행·링크·지원 기록은 그대로 하나). 기존 행은 비워 두고
다음 수집 때 무변경 공고도 채운다(upsert `_BACKFILL_IF_EMPTY`). 데이터 삭제·변환 없음.

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-29 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '0022'
down_revision: Union[str, Sequence[str], None] = '0021'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('job_postings', sa.Column('recruit_fields', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('job_postings', 'recruit_fields')
