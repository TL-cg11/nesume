"""c4 posting career edu text

공고 상세 화면에 "경력: … / 학력: …"을 원문 글로 보여주기 위한 표시용 컬럼(docs C-frontend-wiring.md 8절).
서울시는 응답의 CAREER·MIN/MAX_EDUBG 글, 공채속보는 모집분야별 empWantedCareerNm·empWantedEduNm.
기존 행은 NULL — 다음 수집 때 채워진다. 식별(content_hash)에는 쓰지 않는다.

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-28 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0018'
down_revision: Union[str, Sequence[str], None] = '0017'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('job_postings', sa.Column('career_text', sa.Text(), nullable=True))
    op.add_column('job_postings', sa.Column('edu_text', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('job_postings', 'edu_text')
    op.drop_column('job_postings', 'career_text')
