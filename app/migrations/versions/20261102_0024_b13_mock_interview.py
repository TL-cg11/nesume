"""b13 mock interview

B13을 대화형 모의 면접으로 대체(11/2 사용자 결정, part2_guide 4.72).
0023의 질문 목록 방식(interview_questions, practice_answers)은 그 대응표와 함께 지우고
interview_sessions(면접 한 번)·interview_messages(대화)를 만든다. 개인 등급, 멘토 공유 제외.

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-02 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '0024'
down_revision: Union[str, Sequence[str], None] = '0023'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_GRADES = "grade IN ('public', 'internal', 'personal', 'sensitive', 'confidential')"


def _drop_old_with_vaults() -> None:
    # 대응표는 FK NO ACTION이라 참조 행을 지운 뒤에 지운다(4.33)
    op.execute("CREATE TEMP TABLE _b13_old_vaults ON COMMIT DROP AS "
               "SELECT vault_id FROM practice_answers WHERE vault_id IS NOT NULL "
               "UNION SELECT vault_id FROM interview_questions WHERE vault_id IS NOT NULL")
    op.drop_index(op.f('ix_practice_answers_question_id'), table_name='practice_answers')
    op.drop_index(op.f('ix_practice_answers_owner_id'), table_name='practice_answers')
    op.drop_table('practice_answers')
    op.drop_index(op.f('ix_interview_questions_resume_id'), table_name='interview_questions')
    op.drop_index(op.f('ix_interview_questions_owner_id'), table_name='interview_questions')
    op.drop_table('interview_questions')
    op.execute("DELETE FROM pii_vaults WHERE id IN (SELECT vault_id FROM _b13_old_vaults)")


def upgrade() -> None:
    _drop_old_with_vaults()
    op.create_table('interview_sessions',
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('owner_id', sa.String(length=128), nullable=False),
    sa.Column('resume_id', sa.Uuid(), nullable=False),
    sa.Column('version_ids', postgresql.ARRAY(sa.Uuid()), server_default='{}', nullable=False),
    sa.Column('persona', sa.String(length=20), nullable=False),
    sa.Column('main_count', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=10), server_default='active', nullable=False),
    sa.Column('feedback', sa.Text(), nullable=True),
    sa.Column('expected_questions', sa.Text(), nullable=True),
    sa.Column('vault_id', sa.String(length=64), nullable=True),
    sa.Column('grade', sa.String(length=20), server_default='personal', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint(_GRADES, name=op.f('ck_interview_sessions_grade')),
    sa.CheckConstraint("persona IN ('practical', 'personality', 'pressure')",
                       name=op.f('ck_interview_sessions_persona')),
    sa.CheckConstraint("status IN ('active', 'finished')", name=op.f('ck_interview_sessions_status')),
    sa.CheckConstraint('main_count BETWEEN 1 AND 10', name=op.f('ck_interview_sessions_main_count_range')),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_interview_sessions_owner_id_users'),
                            ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['resume_id'], ['resumes.id'], name=op.f('fk_interview_sessions_resume_id_resumes'),
                            ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['vault_id'], ['pii_vaults.id'],
                            name=op.f('fk_interview_sessions_vault_id_pii_vaults')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_interview_sessions'))
    )
    op.create_index(op.f('ix_interview_sessions_owner_id'), 'interview_sessions', ['owner_id'], unique=False)
    op.create_index(op.f('ix_interview_sessions_resume_id'), 'interview_sessions', ['resume_id'], unique=False)
    op.create_table('interview_messages',
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('owner_id', sa.String(length=128), nullable=False),
    sa.Column('session_id', sa.Uuid(), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('role', sa.String(length=12), nullable=False),
    sa.Column('kind', sa.String(length=10), nullable=True),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('vault_id', sa.String(length=64), nullable=True),
    sa.Column('grade', sa.String(length=20), server_default='personal', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint(_GRADES, name=op.f('ck_interview_messages_grade')),
    sa.CheckConstraint("role IN ('interviewer', 'candidate')", name=op.f('ck_interview_messages_role')),
    sa.CheckConstraint("kind IS NULL OR kind IN ('main', 'follow_up', 'closing')",
                       name=op.f('ck_interview_messages_kind')),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_interview_messages_owner_id_users'),
                            ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['session_id'], ['interview_sessions.id'],
                            name=op.f('fk_interview_messages_session_id_interview_sessions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['vault_id'], ['pii_vaults.id'],
                            name=op.f('fk_interview_messages_vault_id_pii_vaults')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_interview_messages')),
    sa.UniqueConstraint('session_id', 'seq', name=op.f('uq_interview_messages_session_id_seq'))
    )
    op.create_index(op.f('ix_interview_messages_owner_id'), 'interview_messages', ['owner_id'], unique=False)
    op.create_index(op.f('ix_interview_messages_session_id'), 'interview_messages', ['session_id'], unique=False)


def downgrade() -> None:
    # 대화형 기록은 되돌릴 곳이 없어 대응표와 함께 지우고, 0023 테이블은 빈 상태로 다시 만든다
    op.execute("CREATE TEMP TABLE _b13_new_vaults ON COMMIT DROP AS "
               "SELECT vault_id FROM interview_messages WHERE vault_id IS NOT NULL "
               "UNION SELECT vault_id FROM interview_sessions WHERE vault_id IS NOT NULL")
    op.drop_index(op.f('ix_interview_messages_session_id'), table_name='interview_messages')
    op.drop_index(op.f('ix_interview_messages_owner_id'), table_name='interview_messages')
    op.drop_table('interview_messages')
    op.drop_index(op.f('ix_interview_sessions_resume_id'), table_name='interview_sessions')
    op.drop_index(op.f('ix_interview_sessions_owner_id'), table_name='interview_sessions')
    op.drop_table('interview_sessions')
    op.execute("DELETE FROM pii_vaults WHERE id IN (SELECT vault_id FROM _b13_new_vaults)")
    import importlib.util
    from pathlib import Path
    path = Path(__file__).with_name('20261102_0023_b13_interview_practice.py')
    spec = importlib.util.spec_from_file_location('_b13_0023', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.upgrade()
