"""감사 로그 기록 함수 (B11, spec 10.1·10.2). A8 가드레일의 AuditSink 규약 구현.

A8은 요청 종료 시 한 번 `await sink.write(**fields)`를 부른다. 이 함수가 예외를 내면
A8이 AuditWriteFailed로 요청을 실패 처리한다(기록 없는 처리는 없던 일).

- 저장 전에 DB 제약과 같은 규칙으로 먼저 검증해, 실패 이유를 분명한 메시지로 돌려준다.
- 알 수 없는 키는 거부한다(오타·원문 컬럼 유입 방지).
- 요청 트랜잭션과 분리된 자체 트랜잭션으로 커밋한다. 요청이 롤백돼도 감사 로그는 남는다.
"""
import asyncio
import re
import uuid
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import AuditLog
from app.models._common import GRADES
from app.models.audit import DECISION_STAGES, DECISIONS, QUERY_TYPES, ROLES, TEST_SESSION_PREFIX

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class AuditRecord(BaseModel):
    """spec 10.1 필드. timestamp·grade는 DB 기본값."""

    model_config = ConfigDict(extra="forbid")

    request_id: uuid.UUID
    session_id: str = Field(max_length=128)
    user_id: str = Field(min_length=1, max_length=128)
    role: str
    feature: str = Field(min_length=1, max_length=50)
    query_masked: str | None = None
    query_hash: str | None = None
    query_type: str | None = None
    flags: list[str] = Field(default_factory=list)
    rule_id: str | None = Field(default=None, max_length=50)
    doc_ids: list[str] = Field(default_factory=list)
    doc_grades: list[str] = Field(default_factory=list)
    decision: str
    decision_stage: str | None = None
    canary_hit: bool = False
    is_test: bool = False
    latency_ms: int | None = None

    @model_validator(mode="after")
    def _check(self):
        errors = []
        if self.role not in ROLES:
            errors.append(f"role={self.role!r}")
        if self.decision not in DECISIONS:
            errors.append(f"decision={self.decision!r}")
        if self.query_type is not None and self.query_type not in QUERY_TYPES:
            errors.append(f"query_type={self.query_type!r}")
        if self.decision_stage is not None and self.decision_stage not in DECISION_STAGES:
            errors.append(f"decision_stage={self.decision_stage!r}")
        if self.query_hash is not None and not _SHA256.match(self.query_hash):
            errors.append("query_hash must be lowercase SHA-256 hex")
        unknown = [g for g in self.doc_grades if g not in GRADES]
        if unknown:
            errors.append(f"doc_grades={unknown!r}")
        if len(self.doc_ids) != len(self.doc_grades):
            errors.append("doc_ids and doc_grades must have the same length")
        if self.session_id.startswith(TEST_SESSION_PREFIX) != self.is_test:
            errors.append(f"is_test must be true iff session_id starts with {TEST_SESSION_PREFIX!r}")
        if errors:
            raise ValueError("; ".join(errors))
        return self


class AuditRecordInvalid(ValueError):
    pass


class DbAuditSink:
    """A8 AuditSink 규약: `async write(**fields) -> None`."""

    def __init__(self, session_factory: Callable[[], Session] = SessionLocal):
        self._session_factory = session_factory

    async def write(self, **fields: object) -> None:
        try:
            record = AuditRecord(**fields)
        except ValidationError as e:
            # 값 자체는 메시지에 넣지 않는다(마스킹 질의 등 민감 등급 데이터)
            raise AuditRecordInvalid(
                "; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors(include_input=False))
            ) from None
        await asyncio.to_thread(self._insert, record)

    def _insert(self, record: AuditRecord) -> None:
        with self._session_factory() as db:
            db.add(AuditLog(**record.model_dump()))
            db.commit()
