"""c a models aggregate

C·A 모델 취합(B, tasks.md "모델 추가는 B가 취합"). main 병합(10/23) 시점의 모델 기준.
- C4 수집 기록(collection_runs), C3 임베딩 2종(공고 CASCADE), C14 학습 콘텐츠·로드맵·항목(항목 CASCADE, 콘텐츠 SET NULL)
- A14 말투 프로필(writing_profiles, 사용자 삭제 시 CASCADE)
- learning_roadmaps.job_posting_id FK는 C와 협의 중(part2_guide 4.42). 현재 C 설계대로 FK 없음

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-23 08:50:04.238453

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = '0013'
down_revision: Union[str, Sequence[str], None] = '0012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('collection_runs',
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('received', sa.Integer(), nullable=False),
    sa.Column('healthy', sa.Boolean(), nullable=False),
    sa.Column('reason', sa.String(length=64), nullable=False),
    sa.Column('ran_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_collection_runs'))
    )
    op.create_index(op.f('ix_collection_runs_source'), 'collection_runs', ['source'], unique=False)
    op.create_index('ix_collection_runs_source_ran', 'collection_runs', ['source', 'ran_at'], unique=False)
    op.create_table('learning_contents',
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('external_id', sa.String(length=64), nullable=False),
    sa.Column('mode', sa.String(length=10), server_default='online', nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('provider', sa.Text(), nullable=True),
    sa.Column('est_hours', sa.Float(), nullable=True),
    sa.Column('weeks', sa.Integer(), nullable=True),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('classfy', sa.Text(), nullable=True),
    sa.Column('rating', sa.Float(), nullable=True),
    sa.Column('certificate', sa.Boolean(), nullable=True),
    sa.Column('competency_keys', postgresql.ARRAY(sa.String(length=64)), server_default='{}', nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("mode IN ('online', 'offline')", name=op.f('ck_learning_contents_learning_contents_mode')),
    sa.CheckConstraint("source IN ('kmooc', 'kocw', 'youtube', 'work24', 'user')", name=op.f('ck_learning_contents_learning_contents_source')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_learning_contents'))
    )
    op.create_index(op.f('ix_learning_contents_external_id'), 'learning_contents', ['external_id'], unique=False)
    op.create_index('uq_learning_contents_source_ext', 'learning_contents', ['source', 'external_id'], unique=True)
    op.create_table('learning_roadmaps',
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('owner_id', sa.String(length=128), nullable=False),
    sa.Column('job_posting_id', sa.Uuid(), nullable=True),
    sa.Column('weekly_hours', sa.Integer(), server_default='5', nullable=False),
    sa.Column('explanation', sa.Text(), nullable=True),
    sa.Column('grade', sa.String(length=20), server_default='personal', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("grade IN ('public', 'internal', 'personal', 'sensitive', 'confidential')", name=op.f('ck_learning_roadmaps_grade')),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_learning_roadmaps_owner_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_learning_roadmaps'))
    )
    op.create_index(op.f('ix_learning_roadmaps_job_posting_id'), 'learning_roadmaps', ['job_posting_id'], unique=False)
    op.create_index(op.f('ix_learning_roadmaps_owner_id'), 'learning_roadmaps', ['owner_id'], unique=False)
    op.create_table('user_profile_embeddings',
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('owner_id', sa.String(length=128), nullable=False),
    sa.Column('source_type', sa.String(length=20), nullable=False),
    sa.Column('source_id', sa.Uuid(), nullable=False),
    sa.Column('chunk_index', sa.Integer(), server_default='0', nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('grade', sa.String(length=20), server_default='personal', nullable=False),
    sa.Column('model_version', sa.String(length=64), server_default='bge-m3', nullable=False),
    sa.Column('embedding', Vector(1024), nullable=False),
    sa.Column('shared_with', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("grade IN ('public', 'internal', 'personal', 'sensitive', 'confidential')", name=op.f('ck_user_profile_embeddings_grade')),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_user_profile_embeddings_owner_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_profile_embeddings'))
    )
    op.create_index('ix_upe_hnsw', 'user_profile_embeddings', ['embedding'], unique=False, postgresql_using='hnsw', postgresql_with={'m': 16, 'ef_construction': 64}, postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.create_index(op.f('ix_user_profile_embeddings_model_version'), 'user_profile_embeddings', ['model_version'], unique=False)
    op.create_index(op.f('ix_user_profile_embeddings_owner_id'), 'user_profile_embeddings', ['owner_id'], unique=False)
    op.create_index(op.f('ix_user_profile_embeddings_source_id'), 'user_profile_embeddings', ['source_id'], unique=False)
    op.create_table('writing_profiles',
    sa.Column('owner_id', sa.String(length=128), nullable=False),
    sa.Column('grade', sa.String(length=20), server_default='personal', nullable=False),
    sa.Column('avg_sentence_len', sa.Integer(), nullable=False),
    sa.Column('long_sentence_ratio', sa.Integer(), nullable=False),
    sa.Column('paragraph_avg_sentences', sa.Integer(), nullable=False),
    sa.Column('numeric_density', sa.Integer(), nullable=False),
    sa.Column('endings', postgresql.ARRAY(sa.String(length=20)), server_default='{}', nullable=False),
    sa.Column('connectives', postgresql.ARRAY(sa.String(length=20)), server_default='{}', nullable=False),
    sa.Column('source_chars', sa.Integer(), nullable=False),
    sa.Column('sentence_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("grade IN ('public', 'internal', 'personal', 'sensitive', 'confidential')", name=op.f('ck_writing_profiles_grade')),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_writing_profiles_owner_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('owner_id', name=op.f('pk_writing_profiles'))
    )
    op.create_table('job_posting_embeddings',
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('source_id', sa.Uuid(), nullable=False),
    sa.Column('chunk_index', sa.Integer(), server_default='0', nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('grade', sa.String(length=20), server_default='public', nullable=False),
    sa.Column('model_version', sa.String(length=64), server_default='bge-m3', nullable=False),
    sa.Column('embedding', Vector(1024), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("grade IN ('public', 'internal', 'personal', 'sensitive', 'confidential')", name=op.f('ck_job_posting_embeddings_grade')),
    sa.ForeignKeyConstraint(['source_id'], ['job_postings.id'], name=op.f('fk_job_posting_embeddings_source_id_job_postings'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_job_posting_embeddings'))
    )
    op.create_index(op.f('ix_job_posting_embeddings_model_version'), 'job_posting_embeddings', ['model_version'], unique=False)
    op.create_index(op.f('ix_job_posting_embeddings_source_id'), 'job_posting_embeddings', ['source_id'], unique=False)
    op.create_index('ix_jpe_hnsw', 'job_posting_embeddings', ['embedding'], unique=False, postgresql_using='hnsw', postgresql_with={'m': 16, 'ef_construction': 64}, postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.create_table('learning_roadmap_items',
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('roadmap_id', sa.Uuid(), nullable=False),
    sa.Column('content_id', sa.Uuid(), nullable=True),
    sa.Column('origin', sa.String(length=8), server_default='system', nullable=False),
    sa.Column('week', sa.Integer(), nullable=True),
    sa.Column('position', sa.Integer(), server_default='0', nullable=False),
    sa.Column('status', sa.String(length=12), server_default='planned', nullable=False),
    sa.Column('title', sa.Text(), nullable=True),
    sa.Column('url', sa.Text(), nullable=True),
    sa.Column('hours', sa.Float(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("origin IN ('system', 'user')", name=op.f('ck_learning_roadmap_items_learning_roadmap_items_origin')),
    sa.CheckConstraint("status IN ('planned', 'in_progress', 'done')", name=op.f('ck_learning_roadmap_items_learning_roadmap_items_status')),
    sa.ForeignKeyConstraint(['content_id'], ['learning_contents.id'], name=op.f('fk_learning_roadmap_items_content_id_learning_contents'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['roadmap_id'], ['learning_roadmaps.id'], name=op.f('fk_learning_roadmap_items_roadmap_id_learning_roadmaps'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_learning_roadmap_items'))
    )
    op.create_index(op.f('ix_learning_roadmap_items_content_id'), 'learning_roadmap_items', ['content_id'], unique=False)
    op.create_index(op.f('ix_learning_roadmap_items_roadmap_id'), 'learning_roadmap_items', ['roadmap_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_learning_roadmap_items_roadmap_id'), table_name='learning_roadmap_items')
    op.drop_index(op.f('ix_learning_roadmap_items_content_id'), table_name='learning_roadmap_items')
    op.drop_table('learning_roadmap_items')
    op.drop_index('ix_jpe_hnsw', table_name='job_posting_embeddings', postgresql_using='hnsw', postgresql_with={'m': 16, 'ef_construction': 64}, postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.drop_index(op.f('ix_job_posting_embeddings_source_id'), table_name='job_posting_embeddings')
    op.drop_index(op.f('ix_job_posting_embeddings_model_version'), table_name='job_posting_embeddings')
    op.drop_table('job_posting_embeddings')
    op.drop_table('writing_profiles')
    op.drop_index(op.f('ix_user_profile_embeddings_source_id'), table_name='user_profile_embeddings')
    op.drop_index(op.f('ix_user_profile_embeddings_owner_id'), table_name='user_profile_embeddings')
    op.drop_index(op.f('ix_user_profile_embeddings_model_version'), table_name='user_profile_embeddings')
    op.drop_index('ix_upe_hnsw', table_name='user_profile_embeddings', postgresql_using='hnsw', postgresql_with={'m': 16, 'ef_construction': 64}, postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.drop_table('user_profile_embeddings')
    op.drop_index(op.f('ix_learning_roadmaps_owner_id'), table_name='learning_roadmaps')
    op.drop_index(op.f('ix_learning_roadmaps_job_posting_id'), table_name='learning_roadmaps')
    op.drop_table('learning_roadmaps')
    op.drop_index('uq_learning_contents_source_ext', table_name='learning_contents')
    op.drop_index(op.f('ix_learning_contents_external_id'), table_name='learning_contents')
    op.drop_table('learning_contents')
    op.drop_index('ix_collection_runs_source_ran', table_name='collection_runs')
    op.drop_index(op.f('ix_collection_runs_source'), table_name='collection_runs')
    op.drop_table('collection_runs')
