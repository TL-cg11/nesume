"""c14 roadmap items gap/match, learning content embeddings, drop explanation

① `learning_roadmap_items`에 `gap_key`·`gap_label`·`match_kind` — 항목이 어느 역량 몫인지·강좌를 어떻게
   찾았는지(key/title/semantic). "이 역량 강좌 전체 보기"·교체·"AI 추천" 배지에 쓴다. 기존 행은 NULL.
② `learning_content_embeddings` — 강좌 의미 검색(bge-m3, 1024, 코사인 HNSW). 강좌당 1행, grade=public.
③ `learning_roadmaps.explanation` 삭제 — "왜 이 순서인지" LLM 설명 제거(2026-10-29, docs/C14.md).
④ `learning_roadmaps.mode` — 만들 때 고른 학습 방법(NULL=전체). 로드맵 여러 개를 목록에서 구분해 연다.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-29 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
from pgvector.sqlalchemy import Vector
import sqlalchemy as sa


revision: str = '0020'
down_revision: Union[str, Sequence[str], None] = '0019'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_HNSW = dict(
    postgresql_using='hnsw',
    postgresql_with={'m': 16, 'ef_construction': 64},
    postgresql_ops={'embedding': 'vector_cosine_ops'},
)


def upgrade() -> None:
    op.add_column('learning_roadmap_items', sa.Column('gap_key', sa.Text(), nullable=True))
    op.add_column('learning_roadmap_items', sa.Column('gap_label', sa.Text(), nullable=True))
    op.add_column('learning_roadmap_items', sa.Column('match_kind', sa.String(length=12), nullable=True))
    op.create_check_constraint(
        op.f('ck_learning_roadmap_items_learning_roadmap_items_match_kind'),
        'learning_roadmap_items',
        "match_kind IN ('key', 'title', 'semantic')",
    )

    op.create_table('learning_content_embeddings',
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('content_id', sa.Uuid(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('grade', sa.String(length=20), server_default='public', nullable=False),
    sa.Column('model_version', sa.String(length=64), server_default='bge-m3', nullable=False),
    sa.Column('embedding', Vector(1024), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("grade IN ('public', 'internal', 'personal', 'sensitive', 'confidential')", name=op.f('ck_learning_content_embeddings_grade')),
    sa.ForeignKeyConstraint(['content_id'], ['learning_contents.id'], name=op.f('fk_learning_content_embeddings_content_id_learning_contents'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_learning_content_embeddings')),
    sa.UniqueConstraint('content_id', name=op.f('uq_learning_content_embeddings_content_id'))
    )
    op.create_index(op.f('ix_learning_content_embeddings_model_version'), 'learning_content_embeddings', ['model_version'], unique=False)
    op.create_index('ix_lce_hnsw', 'learning_content_embeddings', ['embedding'], unique=False, **_HNSW)

    op.drop_column('learning_roadmaps', 'explanation')
    op.add_column('learning_roadmaps', sa.Column('mode', sa.String(length=10), nullable=True))
    op.create_check_constraint(
        op.f('ck_learning_roadmaps_learning_roadmaps_mode'), 'learning_roadmaps', "mode IN ('online', 'offline')"
    )


def downgrade() -> None:
    op.drop_constraint(op.f('ck_learning_roadmaps_learning_roadmaps_mode'), 'learning_roadmaps', type_='check')
    op.drop_column('learning_roadmaps', 'mode')
    op.add_column('learning_roadmaps', sa.Column('explanation', sa.Text(), nullable=True))

    op.drop_index('ix_lce_hnsw', table_name='learning_content_embeddings', **_HNSW)
    op.drop_index(op.f('ix_learning_content_embeddings_model_version'), table_name='learning_content_embeddings')
    op.drop_table('learning_content_embeddings')

    op.drop_constraint(
        op.f('ck_learning_roadmap_items_learning_roadmap_items_match_kind'), 'learning_roadmap_items', type_='check'
    )
    op.drop_column('learning_roadmap_items', 'match_kind')
    op.drop_column('learning_roadmap_items', 'gap_label')
    op.drop_column('learning_roadmap_items', 'gap_key')
