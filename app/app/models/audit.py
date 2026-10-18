"""감사 로그 (spec 10.1). 민감 등급. 요청당 1행, 원문 질의 저장 금지.

user_id는 FK를 두지 않는다. 계정 삭제 시 anon_id로 치환해 보존한다(spec 10.2).
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._common import Grade, grade_check, grade_column, one_of

ROLES = ("user", "mentor", "operator", "system")
QUERY_TYPES = ("normal", "out_of_scope", "sensitive", "exfiltration")
DECISIONS = ("allow", "block", "mask")
DECISION_STAGES = ("classifier", "retriever", "output_guard")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        one_of("role", ROLES, "role"),
        one_of("query_type", QUERY_TYPES, "query_type"),
        one_of("decision", DECISIONS, "decision"),
        one_of("decision_stage", DECISION_STAGES, "decision_stage"),
        grade_check(),
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
