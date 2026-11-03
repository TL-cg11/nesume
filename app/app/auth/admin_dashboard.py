"""운영자 대시보드 API (D15 차단 현황 + D14 트래픽). 화면은 web/src/features/admin/AdminDashboardPage.jsx.

GET /admin/dashboard/summary?hours=24&include_test=false
    B11 감사 로그 테이블(audit_logs)을 집계한다. 판정(allow/mask/block)·유형·역할·기능·단계별 건수,
    시간대별 추이, flag 비율 상위 사용자 10명, 최근 차단·카나리 이벤트, 직전 같은 기간과의 비교.
    is_test(평가 러너 트래픽)는 기본 제외. B11 조회 API 는 집계를 두지 않으므로(문서대로)
    읽기 전용 집계만 여기에 둔다.
    원문 질의는 내려주지 않는다(query_masked 도 제외 — 상세는 AI 사용 기록 화면).
GET /admin/dashboard/traffic?minutes=60
    core/metrics.py 프로세스 내 트래픽 집계(이 파드 기준).
    환경 전체 수치는 CloudWatch 대시보드(infra/modules/observability).

둘 다 운영자 MFA 세션(D7 require_operator_mfa)만 호출할 수 있다.
"""
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import Integer, case, func, literal, select, text
from sqlalchemy.orm import Session

from app.auth.cognito import CurrentUser
from app.auth.dependencies import require_operator_mfa
from app.config import get_settings
from app.core.metrics import WINDOW_MINUTES, traffic
from app.db import get_db
from app.models import AuditLog

router = APIRouter(prefix="/admin/dashboard", tags=["admin"])

Operator = Annotated[CurrentUser, Depends(require_operator_mfa)]
Db = Annotated[Session, Depends(get_db)]

MAX_HOURS = 24 * 14
TOP_USERS = 10
TOP_FEATURES = 12
RECENT_EVENTS = 20


class Totals(BaseModel):
    requests: int
    allow: int
    mask: int
    block: int
    flagged: int
    canary_hits: int
    block_rate: float
    flag_rate: float
    avg_latency_ms: float | None


class Count(BaseModel):
    key: str
    requests: int
    block: int
    mask: int = 0


class SeriesPoint(BaseModel):
    at: datetime
    allow: int
    mask: int
    block: int


class TopUser(BaseModel):
    user_id: str
    role: str
    requests: int
    flagged: int
    block: int
    canary_hits: int
    flag_rate: float


class RecentEvent(BaseModel):
    request_id: uuid.UUID
    timestamp: datetime
    user_id: str
    role: str
    feature: str
    query_type: str | None
    decision: str
    decision_stage: str | None
    rule_id: str | None
    flags: list[str]
    canary_hit: bool
    is_test: bool


class Comparison(BaseModel):
    """직전 같은 길이의 기간. 화면이 증감을 보여준다."""

    requests: int
    block: int
    flagged: int


class Summary(BaseModel):
    env: str
    generated_at: datetime
    window_from: datetime
    window_to: datetime
    hours: int
    step_minutes: int
    include_test: bool
    totals: Totals
    previous: Comparison
    by_decision: list[Count]
    by_query_type: list[Count]
    by_role: list[Count]
    by_feature: list[Count]
    by_stage: list[Count]
    series: list[SeriesPoint]
    top_users: list[TopUser]
    recent_events: list[RecentEvent]


def _step_minutes(hours: int) -> int:
    if hours <= 1:
        return 5
    if hours <= 6:
        return 15
    if hours <= 48:
        return 60
    return 360


_flagged = case((func.cardinality(AuditLog.flags) > 0, 1), else_=0)
_block = case((AuditLog.decision == "block", 1), else_=0)
_mask = case((AuditLog.decision == "mask", 1), else_=0)
_allow = case((AuditLog.decision == "allow", 1), else_=0)
_canary = func.cast(AuditLog.canary_hit, Integer)


def _scoped(stmt, since: datetime, until: datetime, include_test: bool):
    stmt = stmt.where(AuditLog.timestamp >= since, AuditLog.timestamp < until)
    if not include_test:
        stmt = stmt.where(AuditLog.is_test.is_(False))
    return stmt


def _totals(db: Session, since: datetime, until: datetime, include_test: bool) -> Totals:
    row = db.execute(
        _scoped(
            select(
                func.count(),
                func.coalesce(func.sum(_allow), 0),
                func.coalesce(func.sum(_mask), 0),
                func.coalesce(func.sum(_block), 0),
                func.coalesce(func.sum(_flagged), 0),
                func.coalesce(func.sum(_canary), 0),
                func.avg(AuditLog.latency_ms),
            ),
            since,
            until,
            include_test,
        )
    ).one()
    total, allow, mask, block, flagged, canary, avg_latency = row
    return Totals(
        requests=total,
        allow=allow,
        mask=mask,
        block=block,
        flagged=flagged,
        canary_hits=canary,
        block_rate=round(block / total, 4) if total else 0.0,
        flag_rate=round(flagged / total, 4) if total else 0.0,
        avg_latency_ms=round(float(avg_latency), 1) if avg_latency is not None else None,
    )


def _grouped(db: Session, column, since, until, include_test, *, limit: int | None = None) -> list[Count]:
    key = func.coalesce(column, literal("(없음)"))
    stmt = _scoped(
        select(key, func.count(), func.sum(_block), func.sum(_mask))
        .group_by(key)
        .order_by(func.count().desc(), key),
        since,
        until,
        include_test,
    )
    if limit:
        stmt = stmt.limit(limit)
    return [Count(key=k, requests=n, block=b or 0, mask=m or 0) for k, n, b, m in db.execute(stmt)]


def _series(db: Session, since, until, include_test, step: int) -> list[SeriesPoint]:
    interval = text(f"'{step} minutes'::interval")
    bucket = func.date_bin(interval, AuditLog.timestamp, literal(since))
    rows = db.execute(
        _scoped(
            select(bucket, func.sum(_allow), func.sum(_mask), func.sum(_block))
            .group_by(bucket)
            .order_by(bucket),
            since,
            until,
            include_test,
        )
    ).all()
    found = {r[0]: r for r in rows}
    points: list[SeriesPoint] = []
    at = since
    while at < until:
        r = found.get(at)
        allow, mask, block = (r[1] or 0, r[2] or 0, r[3] or 0) if r else (0, 0, 0)
        points.append(SeriesPoint(at=at, allow=allow, mask=mask, block=block))
        at += timedelta(minutes=step)
    return points


def _top_users(db: Session, since, until, include_test) -> list[TopUser]:
    flagged = func.sum(_flagged)
    total = func.count()
    stmt = _scoped(
        select(
            AuditLog.user_id,
            func.max(AuditLog.role),
            total,
            flagged,
            func.sum(_block),
            func.sum(_canary),
        )
        .group_by(AuditLog.user_id)
        .having(flagged > 0)
        .order_by((flagged * 1.0 / total).desc(), flagged.desc(), total.desc(), AuditLog.user_id)
        .limit(TOP_USERS),
        since,
        until,
        include_test,
    )
    return [
        TopUser(
            user_id=uid,
            role=role,
            requests=n,
            flagged=f,
            block=b or 0,
            canary_hits=c or 0,
            flag_rate=round(f / n, 4) if n else 0.0,
        )
        for uid, role, n, f, b, c in db.execute(stmt)
    ]


def _recent_events(db: Session, since, until, include_test) -> list[RecentEvent]:
    stmt = _scoped(
        select(AuditLog)
        .where((AuditLog.decision != "allow") | AuditLog.canary_hit.is_(True))
        .order_by(AuditLog.timestamp.desc(), AuditLog.request_id)
        .limit(RECENT_EVENTS),
        since,
        until,
        include_test,
    )
    return [RecentEvent.model_validate(row, from_attributes=True) for row in db.scalars(stmt)]


@router.get("/summary", response_model=Summary)
def summary(
    _: Operator,
    db: Db,
    hours: Annotated[int, Query(ge=1, le=MAX_HOURS)] = 24,
    include_test: Annotated[bool, Query()] = False,
) -> Summary:
    step = _step_minutes(hours)
    now = datetime.now(UTC)
    # 끝을 버킷 경계에 맞춰 마지막 점이 "진행 중" 구간이 되게 한다
    until = now.replace(second=0, microsecond=0)
    until = until - timedelta(minutes=until.minute % step) + timedelta(minutes=step)
    since = until - timedelta(hours=hours)
    prev_totals = _totals(db, since - timedelta(hours=hours), since, include_test)
    return Summary(
        env=get_settings().app_env,
        generated_at=now,
        window_from=since,
        window_to=until,
        hours=hours,
        step_minutes=step,
        include_test=include_test,
        totals=_totals(db, since, until, include_test),
        previous=Comparison(
            requests=prev_totals.requests, block=prev_totals.block, flagged=prev_totals.flagged
        ),
        by_decision=_grouped(db, AuditLog.decision, since, until, include_test),
        by_query_type=_grouped(db, AuditLog.query_type, since, until, include_test),
        by_role=_grouped(db, AuditLog.role, since, until, include_test),
        by_feature=_grouped(db, AuditLog.feature, since, until, include_test, limit=TOP_FEATURES),
        by_stage=_grouped(db, AuditLog.decision_stage, since, until, include_test),
        series=_series(db, since, until, include_test, step),
        top_users=_top_users(db, since, until, include_test),
        recent_events=_recent_events(db, since, until, include_test),
    )


@router.get("/traffic")
def traffic_snapshot(
    _: Operator,
    minutes: Annotated[int, Query(ge=1, le=WINDOW_MINUTES)] = 60,
) -> dict:
    s = get_settings()
    snap = traffic.snapshot(minutes)
    snap["pod"].update({"version": s.app_version, "env": s.app_env})
    snap["generated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    return snap
