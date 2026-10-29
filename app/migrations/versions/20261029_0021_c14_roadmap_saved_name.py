"""c14 roadmaps saved_at, name (drafts vs saved)

로드맵을 **초안**(saved_at NULL, 사용자당 1개)과 사용자가 [저장]한 **저장본**으로 나눈다. 목록엔 저장본만.
기존 행에는 저장 표시가 없다 → 사용자 결정(2026-10-29, docs/C14.md): **사용자별 최신 1개만 초안으로 남기고
나머지는 삭제**(항목은 FK CASCADE). 되돌려도(downgrade) 지운 로드맵은 돌아오지 않는다.

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-29 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0021'
down_revision: Union[str, Sequence[str], None] = '0020'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('learning_roadmaps', sa.Column('saved_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('learning_roadmaps', sa.Column('name', sa.String(length=200), nullable=True))
    # 사용자별 최신(updated_at, 같으면 created_at·id) 1개만 초안으로 남긴다
    op.execute(
        """
        DELETE FROM learning_roadmaps r
        USING (
            SELECT id, row_number() OVER (
                PARTITION BY owner_id ORDER BY updated_at DESC, created_at DESC, id DESC
            ) AS rn
            FROM learning_roadmaps
        ) o
        WHERE r.id = o.id AND o.rn > 1
        """
    )


def downgrade() -> None:
    op.drop_column('learning_roadmaps', 'name')
    op.drop_column('learning_roadmaps', 'saved_at')
