"""감사 로그 (spec 10.1). 민감 등급. 요청당 1행, 원문 질의 저장 금지(질문·답변 모두 가린 형태로만).

user_id는 FK를 두지 않는다. 계정 삭제 시 anon_id로 치환해 보존한다(spec 10.2).
무결성 제약(B3, part2_guide 4.25): doc_grades 5등급만, test- 접두어⇔is_test, query_hash SHA-256 형식.
보관 90일: features/audit/retention.py 배치가 삭제.
수정·삭제 방지(B11, 마이그레이션 0009 트리거): UPDATE는 user_id를 users.anon_id 값으로 바꾸는 것만,
DELETE는 90일 지난 행만 허용, TRUNCATE 거부.
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, Integer, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._common import GRADES, Grade, grade_check, grade_column, one_of

ROLES = ("user", "mentor", "operator", "system")
QUERY_TYPES = ("normal", "out_of_scope", "sensitive", "exfiltration")
DECISIONS = ("allow", "block", "mask")
DECISION_STAGES = ("classifier", "retriever", "output_guard")
TEST_SESSION_PREFIX = "test-"
_GRADE_ARRAY = "ARRAY[" + ", ".join(f"'{g}'" for g in GRADES) + "]::varchar(20)[]"


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        one_of("role", ROLES, "role"),
        one_of("query_type", QUERY_TYPES, "query_type"),
        one_of("decision", DECISIONS, "decision"),
        one_of("decision_stage", DECISION_STAGES, "decision_stage"),
        grade_check(),
        # B3 무결성 제약 (part2_guide 4.25)
        CheckConstraint(f"doc_grades <@ {_GRADE_ARRAY}", name="doc_grades_known"),
        CheckConstraint(f"(session_id LIKE '{TEST_SESSION_PREFIX}%') = is_test", name="test_session_matches_flag"),
        CheckConstraint("query_hash IS NULL OR query_hash ~ '^[0-9a-f]{64}$'", name="query_hash_sha256"),
        # B11: A8은 doc_ids·doc_grades를 같은 순서로 1:1 기록한다
        CheckConstraint("cardinality(doc_ids) = cardinality(doc_grades)", name="doc_ids_grades_paired"),
        Index("ix_audit_logs_user_ts", "user_id", "timestamp"),
        Index("ix_audit_logs_ts", "timestamp"),
    )

    request_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(128))  # 테스트 트래픽은 test- 접두어
    user_id: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(20))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    feature: Mapped[str] = mapped_column(String(50))
    query_masked: Mapped[str | None] = mapped_column(Text)  # A1 마스킹 적용
    # 사용자에게 돌려준 답변(복원 전 토큰 + 마스킹). 차단 시 NULL(막힌 응답은 남기지 않음, part2_guide 4.74)
    response_masked: Mapped[str | None] = mapped_column(Text)
    query_hash: Mapped[str | None] = mapped_column(String(64))  # 원문 SHA-256 hex
    query_type: Mapped[str | None] = mapped_column(String(20))
    flags: Mapped[list[str]] = mapped_column(ARRAY(String(50)), default=list, server_default="{}")
    rule_id: Mapped[str | None] = mapped_column(String(50))
    doc_ids: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list, server_default="{}")
    doc_grades: Mapped[list[str]] = mapped_column(ARRAY(String(20)), default=list, server_default="{}")
    decision: Mapped[str] = mapped_column(String(10))
    decision_stage: Mapped[str | None] = mapped_column(String(20))
    canary_hit: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_test: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    # 감사 로그 자체의 등급(spec 10.2: 민감)
    grade: Mapped[str] = grade_column(Grade.SENSITIVE)
