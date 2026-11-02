"""b13 interview practice

B13 면접 예상 질문·답변 연습(spec 3.3, part2_guide 4.71). 개인 등급, 멘토 공유 제외.
본문은 PII 토큰화 상태 + 대응표(vault_id). 자소서·계정 삭제 시 CASCADE, 대응표는 B20 물리 삭제에서 정리.

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-02 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '0023'
down_revision: Union[str, Sequence[str], None] = '0022'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_GRADES = "grade IN ('public', 'internal', 'personal', 'sensitive', 'confidential')"


def upgrade() -> None:
    op.create_table('interview_questions',
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('owner_id', sa.String(length=128), nullable=False),
    sa.Column('resume_id', sa.Uuid(), nullable=False),
    sa.Column('version_ids', postgresql.ARRAY(sa.Uuid()), server_default='{}', nullable=False),
    sa.Column('type', sa.String(length=20), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('vault_id', sa.String(length=64), nullable=True),
    sa.Column('grade', sa.String(length=20), server_default='personal', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint(_GRADES, name=op.f('ck_interview_questions_grade')),
    sa.CheckConstraint("type IN ('personality', 'job', 'experience')", name=op.f('ck_interview_questions_type')),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_interview_questions_owner_id_users'),
                            ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['resume_id'], ['resumes.id'], name=op.f('fk_interview_questions_resume_id_resumes'),
                            ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['vault_id'], ['pii_vaults.id'], name=op.f('fk_interview_questions_vault_id_pii_vaults')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_interview_questions'))
    )
    op.create_index(op.f('ix_interview_questions_owner_id'), 'interview_questions', ['owner_id'], unique=False)
    op.create_index(op.f('ix_interview_questions_resume_id'), 'interview_questions', ['resume_id'], unique=False)
    op.create_table('practice_answers',
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('owner_id', sa.String(length=128), nullable=False),
    sa.Column('question_id', sa.Uuid(), nullable=False),
    sa.Column('answer', sa.Text(), nullable=False),
    sa.Column('feedback', sa.Text(), nullable=True),
    sa.Column('vault_id', sa.String(length=64), nullable=True),
    sa.Column('grade', sa.String(length=20), server_default='personal', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint(_GRADES, name=op.f('ck_practice_answers_grade')),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_practice_answers_owner_id_users'),
                            ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['question_id'], ['interview_questions.id'],
                            name=op.f('fk_practice_answers_question_id_interview_questions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['vault_id'], ['pii_vaults.id'], name=op.f('fk_practice_answers_vault_id_pii_vaults')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_practice_answers'))
    )
    op.create_index(op.f('ix_practice_answers_owner_id'), 'practice_answers', ['owner_id'], unique=False)
    op.create_index(op.f('ix_practice_answers_question_id'), 'practice_answers', ['question_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_practice_answers_question_id'), table_name='practice_answers')
    op.drop_index(op.f('ix_practice_answers_owner_id'), table_name='practice_answers')
    op.drop_table('practice_answers')
    op.drop_index(op.f('ix_interview_questions_resume_id'), table_name='interview_questions')
    op.drop_index(op.f('ix_interview_questions_owner_id'), table_name='interview_questions')
    op.drop_table('interview_questions')
