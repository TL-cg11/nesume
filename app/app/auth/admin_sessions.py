"""운영자용 세션 차단 API (D16). 화면은 web/src/features/admin/AdminSessionsPage.jsx.

GET    /admin/sessions/blocked?active=true      차단 목록(기본 유효한 것만. active=false 면 해제·만료 이력
포함, 최근 200건)
POST   /admin/sessions/{session_id}/block        수동 차단 body {"note": "...", "minutes": null}  (minutes
없으면 해제까지)
DELETE /admin/sessions/{session_id}/block        차단 해제

자동 차단(카나리·탈취 임계치)은 core/session_block.py 래퍼가 같은 표에 넣는다. 여기서는 목록·수동 차단·해제만.
세 동작 모두 `nesume.audit.admin` 감사 로그 1줄 + 차단·해제는 D16 알림(info).
운영자 판정은 D7 require_operator_mfa(operator + TOTP 등록 + 최근 로그인) — 해제는 MFA 세션에서만 된다는
D16 요구와 같다.
"""
import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.cognito import CurrentUser
from app.auth.dependencies import require_operator_mfa
from app.core import session_block
from app.core.alerts import emit
from app.core.errors import NotFoundError
from app.db import get_db
from app.models.blocked_session import BlockedSession

audit_log = logging.getLogger("nesume.audit.admin")

router = APIRouter(prefix="/admin/sessions", tags=["admin"])

Operator = Annotated[CurrentUser, Depends(require_operator_mfa)]
Db = Annotated[Session, Depends(get_db)]
# X-Session-Id 규약(guardrail/fastapi.py guardrail_kwargs): 128자 이하. 경로에 제어문자·공백은 받지 않는다
SessionId = Annotated[str, Path(min_length=1, max_length=128, pattern=r"^[^\s/\x00-\x1f]+$")]

MAX_BLOCK_MINUTES = 60 * 24 * 30


class BlockIn(BaseModel):
    note: str | None = Field(default=None, max_length=300)
    # 없으면 운영자가 풀 때까지. 있으면 그 시간(분) 뒤 자동 만료
    minutes: int | None = Field(default=None, ge=1, le=MAX_BLOCK_MINUTES)


class BlockedSessionOut(BaseModel):
    session_id: str
    user_id: str
    reason: str
    rule_id: str | None
    note: str | None
    blocked_by: str
    expires_at: datetime | None
    released_at: datetime | None
    released_by: str | None
    created_at: datetime
    active: bool


def _out(row: BlockedSession, now: datetime) -> BlockedSessionOut:
    active = session_block.is_active(row, now)
    return BlockedSessionOut(
        session_id=row.session_id, user_id=row.user_id, reason=row.reason, rule_id=row.rule_id,
        note=row.note, blocked_by=row.blocked_by, expires_at=row.expires_at, released_at=row.released_at,
        released_by=row.released_by, created_at=row.created_at, active=active,
    )


@router.get("/blocked", response_model=list[BlockedSessionOut])
def list_blocked(
    _: Operator,
    db: Db,
    active: Annotated[bool, Query()] = True,
) -> list[BlockedSessionOut]:
    now = datetime.now(UTC)
    return [_out(r, now) for r in session_block.list_blocks(db, active_only=active, now=now)]


@router.post("/{session_id}/block", response_model=BlockedSessionOut)
def block_session(
    session_id: SessionId,
    body: BlockIn,
    actor: Operator,
    db: Db,
) -> BlockedSessionOut:
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=body.minutes) if body.minutes else None
    existing = db.get(BlockedSession, session_id)
    # 수동 차단은 사용자를 모를 수 있다(세션 ID 만 보고 막는 경우). 감사 로그·이전 차단에서 찾고 없으면
    # "unknown"
    user_id = existing.user_id if existing is not None else _user_of_session(db, session_id)
    row, created = session_block.block(
        db, session_id, user_id=user_id, reason="operator", note=body.note,
        blocked_by=actor.sub, expires_at=expires_at, now=now,
    )
    audit_log.info(
        "session_blocked",
        extra={"fields": {
            "session_id": session_id, "user_id": row.user_id, "actor": actor.sub,
            "expires_at": expires_at.isoformat() if expires_at else None, "renewed": not created,
        }},
    )
    emit("session_blocked", f"운영자 수동 차단{' (갱신)' if not created else ''}", session_id=session_id,
         user_id=row.user_id)
    return _out(row, now)


@router.delete("/{session_id}/block", response_model=BlockedSessionOut)
def release_session(session_id: SessionId, actor: Operator, db: Db) -> BlockedSessionOut:
    now = datetime.now(UTC)
    row = session_block.release(db, session_id, released_by=actor.sub, now=now)
    if row is None:
        raise NotFoundError("차단 중인 세션이 아닙니다.")
    audit_log.info(
        "session_released",
        extra={"fields": {"session_id": session_id, "user_id": row.user_id, "actor": actor.sub,
                          "reason": row.reason}},
    )
    emit("session_released", f"운영자 차단 해제 (원래 사유 {row.reason})", session_id=session_id,
         user_id=row.user_id)
    return _out(row, now)


def _user_of_session(db: Session, session_id: str) -> str:
    """감사 로그(B11)에서 이 세션의 최근 사용자. 없으면 'unknown'."""
    from sqlalchemy import select

    from app.models import AuditLog

    found = db.execute(
        select(AuditLog.user_id).where(AuditLog.session_id == session_id)
        .order_by(AuditLog.timestamp.desc()).limit(1)
    ).scalar()
    return found or "unknown"
