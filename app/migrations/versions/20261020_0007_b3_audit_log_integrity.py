"""b3 audit log integrity

B3: 감사 로그 무결성 CHECK 제약 3종(part2_guide 4.25).
- doc_grades 원소는 등급 5종만
- session_id 'test-' 접두어 ⇔ is_test (spec 10.1 "테스트 트래픽은 test- 접두어")
- query_hash는 NULL 또는 SHA-256 소문자 16진수 64자 (원문이 해시 칸에 들어가는 사고 방지)
doc_ids·doc_grades 길이 일치는 A팀(A8) 기록 형식 합의 후 추가.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-20

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

GRADE_ARRAY = "ARRAY['public', 'internal', 'personal', 'sensitive', 'confidential']::varchar(20)[]"
CONSTRAINTS = {
    "ck_audit_logs_doc_grades_known": f"doc_grades <@ {GRADE_ARRAY}",
    "ck_audit_logs_test_session_matches_flag": "(session_id LIKE 'test-%') = is_test",
    "ck_audit_logs_query_hash_sha256": "query_hash IS NULL OR query_hash ~ '^[0-9a-f]{64}$'",
}


def upgrade() -> None:
    for name, condition in CONSTRAINTS.items():
        op.create_check_constraint(op.f(name), "audit_logs", condition)


def downgrade() -> None:
    for name in reversed(CONSTRAINTS):
        op.drop_constraint(op.f(name), "audit_logs", type_="check")
