"""C15 — 지원 현황 서비스 (DB). B `Application` 모델 위 CRUD·상태 전이·집계·마감 임박.

- **본인 전용**: 모든 작업은 `owner_id`로 소유 확인(지원 기록은 grade=personal, 공유 없음).
- **삭제 = hard delete**(결정 2026-10-22): `Application` 모델에 soft-delete 필드 없음.
- **공고 참조 안전**: `job_posting_id`는 C4 내부 UUID → 공고가 비활성/변경돼도 기록 유지.
  목록은 outer join이라 공고가 사라져도(또는 user 입력 공고로 없어도) 지원 기록은 나온다.

DB 필요 — 실행 검증은 CI/통합. 순수 판정은 `rules.py`.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.features.applications.rules import DUE_SOON_DAYS
from app.models.application import APPLICATION_STATUSES, Application
from app.models.posting import JobPosting


class ApplicationNotFound(Exception):
    """해당 사용자의 지원 기록이 아니거나 존재하지 않음."""


def _owned(session: Session, app_id: uuid.UUID, owner_id: str) -> Application:
    app = session.get(Application, app_id)
    if app is None or app.owner_id != owner_id:
        raise ApplicationNotFound(str(app_id))
    return app


def create_application(
    session: Session,
    *,
    owner_id: str,
    status: str,
    job_posting_id: uuid.UUID | None = None,
    resume_id: uuid.UUID | None = None,
    version_ids: list[uuid.UUID] | None = None,
    applied_at: date | None = None,
    memo: str | None = None,
) -> Application:
    """지원 기록 추가. status는 5단계 중 하나(모델 CHECK와 동일 검증)."""
    if status not in APPLICATION_STATUSES:
        raise ValueError(f"unknown status: {status}")
    app = Application(
        owner_id=owner_id,
        job_posting_id=job_posting_id,
        resume_id=resume_id,
        version_ids=version_ids or [],
        status=status,
        applied_at=applied_at,
        memo=memo,
    )
    session.add(app)
    return app


def update_status(session: Session, *, app_id: uuid.UUID, owner_id: str, status: str) -> Application:
    """상태 전이(칸반 이동). 본인 기록만."""
    if status not in APPLICATION_STATUSES:
        raise ValueError(f"unknown status: {status}")
    app = _owned(session, app_id, owner_id)
    app.status = status
    return app


def delete_application(session: Session, *, app_id: uuid.UUID, owner_id: str) -> None:
    """지원 기록 삭제(hard delete). 본인 기록만. 공고 참조가 풀린다(FK RESTRICT 해제 쪽)."""
    session.delete(_owned(session, app_id, owner_id))


def list_applications(session: Session, *, owner_id: str) -> list[tuple[Application, JobPosting | None]]:
    """본인 지원 기록 + 공고(있으면). 공고 비활성/부재여도 기록은 나온다(outer join)."""
    return list(
        session.execute(
            select(Application, JobPosting)
            .outerjoin(JobPosting, JobPosting.id == Application.job_posting_id)
            .where(Application.owner_id == owner_id)
            .order_by(Application.updated_at.desc())
        ).all()
    )


def aggregate_by_status(session: Session, *, owner_id: str) -> dict[str, int]:
    """상태별 건수(칸반 집계). 5단계 전부 0으로 채운 뒤 실제 건수 반영."""
    counts = dict.fromkeys(APPLICATION_STATUSES, 0)
    rows = session.execute(
        select(Application.status, func.count())
        .where(Application.owner_id == owner_id)
        .group_by(Application.status)
    ).all()
    for status, n in rows:
        counts[status] = n
    return counts


def due_soon(
    session: Session,
    *,
    owner_id: str,
    within_days: int = DUE_SOON_DAYS,
    today: date | None = None,
) -> list[tuple[Application, JobPosting]]:
    """마감 임박(오늘~within일) 지원 기록 + 공고. 상시채용(closes_on NULL)·지난 마감 제외."""
    today = today or date.today()
    cutoff = today + timedelta(days=within_days)
    return list(
        session.execute(
            select(Application, JobPosting)
            .join(JobPosting, JobPosting.id == Application.job_posting_id)
            .where(
                Application.owner_id == owner_id,
                JobPosting.closes_on.is_not(None),
                JobPosting.closes_on >= today,
                JobPosting.closes_on <= cutoff,
            )
        ).all()
    )
