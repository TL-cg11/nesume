"""b11 audit log guard

B11: 감사 로그 수정·삭제 방지(팀 합의, part2_guide 4.25·4.29)와 doc_ids·doc_grades 길이 일치 제약.
- UPDATE: user_id를 users.anon_id에 있는 값으로 바꾸는 익명화(B20)만 허용. 다른 컬럼 변경은 거부
- DELETE: 보관 기간(90일, spec 10.2)이 지난 행만 허용(B3 정리 배치)
- TRUNCATE: 거부
DB 관리자는 트리거를 끌 수 있으므로 계정 권한 분리(D)와는 별개의 방어선이다.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-21

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0009"
down_revision: Union[str, Sequence[str], None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# features/audit/retention.RETENTION 과 같은 값(테스트로 일치 확인)
RETENTION_INTERVAL = "90 days"


def upgrade() -> None:
    op.create_check_constraint(
        op.f("ck_audit_logs_doc_ids_grades_paired"), "audit_logs",
        "cardinality(doc_ids) = cardinality(doc_grades)",
    )
    op.execute(f"""
        CREATE FUNCTION audit_logs_guard() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                IF (to_jsonb(NEW) - 'user_id') IS DISTINCT FROM (to_jsonb(OLD) - 'user_id') THEN
                    RAISE EXCEPTION 'audit_logs rows are immutable' USING ERRCODE = 'restrict_violation';
                END IF;
                IF NOT EXISTS (SELECT 1 FROM users WHERE anon_id = NEW.user_id) THEN
                    RAISE EXCEPTION 'audit_logs user_id may only be replaced with an anonymization token'
                        USING ERRCODE = 'restrict_violation';
                END IF;
                RETURN NEW;
            ELSIF TG_OP = 'DELETE' THEN
                IF OLD.timestamp >= now() - interval '{RETENTION_INTERVAL}' THEN
                    RAISE EXCEPTION 'audit_logs rows within retention cannot be deleted'
                        USING ERRCODE = 'restrict_violation';
                END IF;
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'audit_logs cannot be truncated' USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER audit_logs_guard_row BEFORE UPDATE OR DELETE ON audit_logs
        FOR EACH ROW EXECUTE FUNCTION audit_logs_guard()
    """)
    op.execute("""
        CREATE TRIGGER audit_logs_guard_truncate BEFORE TRUNCATE ON audit_logs
        FOR EACH STATEMENT EXECUTE FUNCTION audit_logs_guard()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_logs_guard_truncate ON audit_logs")
    op.execute("DROP TRIGGER IF EXISTS audit_logs_guard_row ON audit_logs")
    op.execute("DROP FUNCTION IF EXISTS audit_logs_guard()")
    op.drop_constraint(op.f("ck_audit_logs_doc_ids_grades_paired"), "audit_logs", type_="check")
