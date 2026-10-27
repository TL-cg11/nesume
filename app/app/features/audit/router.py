"""감사 로그 조회 API (B11, spec 10.3). 운영자 전용.

필터: 기간·user_id·role·feature·query_type·decision·is_test (tasks B11) + request_id(B16 러너).
D15 대시보드와 B16 평가 러너가 같은 API를 쓴다. 집계 API는 두지 않는다(문서대로).
운영자 판정은 토큰 역할만 확인한다. MFA 세션 확인은 D7 공통 모듈로 교체 예정.
doc_ids는 문서 삭제의 "참조"에 포함하지 않으므로 고아 ID일 수 있다(A·C 합의). 문서 테이블과 조인하지 않는다.
"""
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import AuthenticatedUser, CurrentUser, Role
from app.db import get_db
from app.models import AuditLog

DEFAULT_LIMIT = 50
MAX_LIMIT = 500

router = APIRouter(prefix="/audit-logs", tags=["audit"])


def require_operator(user: AuthenticatedUser) -> CurrentUser:
    if user.role != Role.OPERATOR:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")
    return user


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    request_id: uuid.UUID
    session_id: str
    user_id: str
    role: str
    timestamp: datetime
    feature: str
    query_masked: str | None
    query_hash: str | None
    query_type: str | None
    flags: list[str]
    rule_id: str | None
    doc_ids: list[str]
    doc_grades: list[str]
    decision: str
    decision_stage: str | None
    canary_hit: bool
    is_test: bool
    latency_ms: int | None


@router.get("", response_model=list[AuditLogOut])
def list_audit_logs(
    _: Annotated[CurrentUser, Depends(require_operator)],
    db: Annotated[Session, Depends(get_db)],
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: Annotated[datetime | None, Query()] = None,
    user_id: Annotated[str | None, Query(max_length=128)] = None,
    role: Annotated[str | None, Query()] = None,
    feature: Annotated[str | None, Query(max_length=50)] = None,
    query_type: Annotated[str | None, Query()] = None,
    decision: Annotated[str | None, Query()] = None,
    is_test: Annotated[bool | None, Query()] = None,
    # 요청 1건의 로그(B16 평가 러너가 X-Request-ID로 찾는다, part2_guide 4.50)
    request_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    stmt = select(AuditLog)
    if from_ is not None:
        stmt = stmt.where(AuditLog.timestamp >= from_)
    if to is not None:
        stmt = stmt.where(AuditLog.timestamp < to)
    for column, value in (
        (AuditLog.user_id, user_id),
        (AuditLog.role, role),
        (AuditLog.feature, feature),
        (AuditLog.query_type, query_type),
        (AuditLog.decision, decision),
        (AuditLog.is_test, is_test),
        (AuditLog.request_id, request_id),
    ):
        if value is not None:
            stmt = stmt.where(column == value)
    stmt = stmt.order_by(AuditLog.timestamp.desc(), AuditLog.request_id).limit(limit).offset(offset)
    return db.scalars(stmt).all()
