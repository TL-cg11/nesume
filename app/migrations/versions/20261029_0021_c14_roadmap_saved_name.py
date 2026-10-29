"""c14 roadmaps saved_at, name (drafts vs saved)

로드맵을 **초안**(saved_at NULL, 사용자당 1개)과 사용자가 [저장]한 **저장본**(사용자당 최대 10개)으로
나눈다. 목록엔 저장본만. 초안 1개는 부분 고유 인덱스로 DB에서도 막는다.

기존 행에는 저장 표시가 없다 → B 검토 반영(2026-10-29, docs/C14.md). 사용자별 최근 순으로
  - 1번째: 초안으로 둔다
  - 2~11번째: 저장본으로 바꾼다(saved_at = updated_at, name = '로드맵 YYYY-MM-DD')
  - 12번째부터: **삭제**(항목은 FK CASCADE). **복구 불가** — downgrade 해도 지운 로드맵은 돌아오지 않는다.

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
    # 사용자별 최근 순위(updated_at, 같으면 created_at·id). 1 = 초안, 2~11 = 저장본, 12~ = 삭제
    ranked = """
        SELECT id, row_number() OVER (
            PARTITION BY owner_id ORDER BY updated_at DESC, created_at DESC, id DESC
        ) AS rn
        FROM learning_roadmaps
    """
    op.execute(f"DELETE FROM learning_roadmaps r USING ({ranked}) o WHERE r.id = o.id AND o.rn > 11")
    op.execute(
        f"""
        UPDATE learning_roadmaps r
        SET saved_at = r.updated_at,
            name = '로드맵 ' || to_char(r.updated_at AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD')
        FROM ({ranked}) o
        WHERE r.id = o.id AND o.rn BETWEEN 2 AND 11
        """
    )
    op.create_index(
        'uq_learning_roadmaps_one_draft', 'learning_roadmaps', ['owner_id'],
        unique=True, postgresql_where=sa.text('saved_at IS NULL'),
    )


def downgrade() -> None:
    op.drop_index('uq_learning_roadmaps_one_draft', table_name='learning_roadmaps')
    op.drop_column('learning_roadmaps', 'name')
    op.drop_column('learning_roadmaps', 'saved_at')
