"""C4 — 공고 upsert + 수집 건강성 게이트.

하루 1회 전량 재수집분을 받아 공고를 적재·갱신하고, 사라진 공고를 처리한다.
식별·재공고 판별은 `identity`(순수)에 맡기고, 여기선 DB 상태 전이와 **게이트**를 집행한다.

건강성 게이트(docs/C4.md): 수집량이 비정상이면(장애 의심) **사라짐 처리를 동결**한다 —
못 받아온 공고를 "마감"으로 오인해 대량 비활성/삭제하는 사고 방지. 모든 경과는 달력일이
아니라 `missing_streak`(정상 수집 미노출 횟수)로 측정해, 장애일엔 시계가 멈춘다.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.posting import CollectionRun, JobPosting
from app.postings.health import DELETE_CANDIDATE_STREAK, GateDecision
from app.postings.identity import (
    Action,
    ExistingPosting,
    classify,
    content_hash,
    is_reliable_key,
    link_key,
)

_KST = ZoneInfo("Asia/Seoul")


#: 무변경 공고에도 비어 있으면 채우는 **표시 전용** 컬럼(content_hash에 안 들어감). 새 컬럼 추가 시 여기에.
_BACKFILL_IF_EMPTY = ("career_text", "edu_text")


def _kst_now() -> datetime:
    return datetime.now(_KST)


# 식별·수명주기는 upsert가 관리하므로 fields에서 제외한다.
_MANAGED = frozenset({
    "id", "source", "link_key", "content_hash", "is_active", "needs_review",
    "missing_streak", "first_seen_at", "last_seen_at", "created_at", "updated_at",
})


def upsert_posting(
    session: Session,
    *,
    source: str,
    fields: Mapping[str, Any],
    now: datetime | None = None,
) -> tuple[JobPosting, Action]:
    """공고 1건 upsert. link_key로 조회 → classify → 신규/복귀/변경/무변경 전이.

    `fields` = 정제된 공고 컬럼(company_name·title·job_content·region_code·job_code·
    work_address·registered_on·source_key 등). 식별·수명주기 컬럼은 upsert가 채운다.
    """
    now = now or _kst_now()
    native_id = fields.get("source_key")
    lk = link_key(
        source=source,
        company=fields.get("company_name"),
        title=fields.get("title"),
        region_code=fields.get("region_code"),
        job_code=fields.get("job_code"),
        work_address=fields.get("work_address"),
        native_id=native_id,
    )
    ch = content_hash(
        company=fields.get("company_name"),
        title=fields.get("title"),
        registered_on=fields.get("registered_on"),
        job_code=fields.get("job_code"),
        region_code=fields.get("region_code"),
        job_content=fields.get("job_content"),
    )
    reliable = is_reliable_key(
        company=fields.get("company_name"), title=fields.get("title"), native_id=native_id
    )
    content = {k: v for k, v in fields.items() if k not in _MANAGED}

    existing = session.execute(
        select(JobPosting)
        .where(JobPosting.source == source, JobPosting.link_key == lk)
        .order_by(JobPosting.last_seen_at.desc())
    ).scalars().first()

    state = (
        ExistingPosting(
            content_hash=existing.content_hash,
            missing_streak=existing.missing_streak,
            is_active=existing.is_active,
        )
        if existing is not None
        else None
    )
    action = classify(state, incoming_content_hash=ch)

    if action is Action.NEW:
        # 재공고(기존이 아직 활성이면) 옛 행을 먼저 비활성 — 부분 유니크(source,link_key,활성) 보호
        if existing is not None and existing.is_active:
            existing.is_active = False
        row = JobPosting(
            source=source, link_key=lk, content_hash=ch, needs_review=not reliable,
            is_active=True, missing_streak=0, first_seen_at=now, last_seen_at=now, **content,
        )
        session.add(row)
        return row, action

    # 같은 공고 — 복귀/변경/무변경 공통: 재활성 + streak 리셋 + last_seen 갱신
    existing.is_active = True
    existing.missing_streak = 0
    existing.last_seen_at = now
    if action in (Action.CONTENT_CHANGED, Action.REACTIVATED):
        existing.content_hash = ch
        existing.needs_review = not reliable
        for k, v in content.items():
            setattr(existing, k, v)
    else:
        # 무변경이라도 **나중에 추가된 표시용 컬럼이 비어 있으면 채운다**(덮어쓰지 않음, 해시·식별 무관).
        # 없으면 기존 행은 내용이 바뀔 때까지 영영 NULL로 남는다(0018 경력·학력 글).
        for k in _BACKFILL_IF_EMPTY:
            if getattr(existing, k) is None and content.get(k) is not None:
                setattr(existing, k, content[k])
    return existing, action


def apply_absences(
    session: Session,
    *,
    source: str,
    seen_link_keys: Iterable[str],
    gate: GateDecision,
    now: datetime | None = None,
) -> int:
    """이번 수집에 없는 활성 공고를 처리한다. 게이트가 막으면 **전부 동결**(사고 방지).

    정상이면: 미노출 공고를 비활성(추천 제외)하고 `missing_streak`를 올린다. 물리 삭제는
    참조 검사가 필요해(FK RESTRICT) 여기서 하지 않고 `delete_candidates`로 분리한다.
    돌려주는 값 = 이번에 비활성 처리한 건수(동결 시 0).
    """
    if not gate.process_absences:
        return 0  # 건강성 게이트: 비정상·부트스트랩이면 사라짐 처리 동결
    _ = now or _kst_now()
    seen = set(seen_link_keys)
    rows = session.execute(
        select(JobPosting).where(JobPosting.source == source, JobPosting.is_active.is_(True))
    ).scalars()
    deactivated = 0
    for row in rows:
        if row.link_key in seen:
            continue
        row.missing_streak += 1
        row.is_active = False  # 오늘 수집에 없음 → 추천 제외(복귀는 재공고 윈도우 내 재활성)
        deactivated += 1
    return deactivated


def delete_candidates(session: Session, *, source: str) -> list[JobPosting]:
    """물리 삭제 후보(비활성 + 오래 미노출). **참조 검사·실삭제는 통합 단계**(FK RESTRICT가 막음).

    백스톱(`BACKSTOP_STREAK`)·삭제 유예(`DELETE_CANDIDATE_STREAK`)를 넘은 비활성 공고를 추린다.
    실제 삭제는 참조(applications·resumes) 없는 건만 — FK RESTRICT가 참조분 삭제를 거부하므로,
    배치는 IntegrityError를 crash 아닌 skip으로 처리해야 한다(docs/C4.md 결정2).
    """
    return list(
        session.execute(
            select(JobPosting).where(
                JobPosting.source == source,
                JobPosting.is_active.is_(False),
                JobPosting.missing_streak > DELETE_CANDIDATE_STREAK,
            )
        ).scalars()
    )


# ---- 수집 이력 (건강성 게이트 기준선) ----

def recent_counts(session: Session, *, source: str, n: int = 7) -> list[int]:
    """최근 '정상(healthy)' 수집 건수 n개(최신순). 게이트 기준선(중앙값) 입력."""
    return list(
        session.execute(
            select(CollectionRun.received)
            .where(CollectionRun.source == source, CollectionRun.healthy.is_(True))
            .order_by(CollectionRun.ran_at.desc())
            .limit(n)
        ).scalars()
    )


def record_run(session: Session, *, source: str, received: int, healthy: bool, reason: str) -> None:
    """이번 수집 1회를 기록(다음 게이트의 기준선 재료)."""
    session.add(CollectionRun(source=source, received=received, healthy=healthy, reason=reason))
