"""C15 — 지원 현황 API (spec 4.5). 본인 전용 CRUD·칸반 집계·마감 임박.

소유 확인은 서비스가 `owner_id`(토큰 `sub`)로 한다 — 남의 기록은 404(`ApplicationNotFound`).
LLM 직접 호출 없음(순수 DB CRUD). main.py 등록은 D에 PR로 요청(features/__init__.py 규칙).
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.auth import AuthenticatedUser
from app.db import get_db
from app.features.applications import service
from app.features.applications.rules import DUE_SOON_DAYS, days_until
from app.features.applications.schemas import (
    ApplicationCreate,
    ApplicationOrder,
    ApplicationOut,
    ApplicationStatusUpdate,
    PostingBrief,
    StatusCounts,
)
from app.models.application import Application
from app.models.posting import JobPosting

router = APIRouter(prefix="/applications", tags=["applications"])
Db = Annotated[Session, Depends(get_db)]

_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


def _to_out(app: Application, posting: JobPosting | None, today: date) -> ApplicationOut:
    out = ApplicationOut.model_validate(app)
    if posting is not None:
        out.posting = PostingBrief.model_validate(posting)
        out.days_until = days_until(posting.closes_on, today)
    return out


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ApplicationOut)
def create_application(payload: ApplicationCreate, user: AuthenticatedUser, db: Db):
    app = service.create_application(
        db,
        owner_id=user.sub,
        status=payload.status.value,
        job_posting_id=payload.job_posting_id,
        resume_id=payload.resume_id,
        version_ids=payload.version_ids,
        applied_at=payload.applied_at,
        memo=payload.memo,
    )
    db.flush()
    return _to_out(app, None, date.today())


@router.get("", response_model=list[ApplicationOut])
def list_applications(user: AuthenticatedUser, db: Db):
    today = date.today()
    return [_to_out(app, posting, today) for app, posting in service.list_applications(db, owner_id=user.sub)]


@router.get("/stats", response_model=StatusCounts)
def status_counts(user: AuthenticatedUser, db: Db):
    """칸반 상태별 집계(5단계 전부 0 포함)."""
    return StatusCounts(**service.aggregate_by_status(db, owner_id=user.sub))


@router.get("/due-soon", response_model=list[ApplicationOut])
def due_soon(
    user: AuthenticatedUser,
    db: Db,
    within_days: Annotated[int, Query(ge=1, le=60)] = DUE_SOON_DAYS,
):
    """마감 임박(오늘~within일) 지원 기록. 상시채용·지난 마감 제외."""
    today = date.today()
    rows = service.due_soon(db, owner_id=user.sub, within_days=within_days, today=today)
    return [_to_out(app, posting, today) for app, posting in rows]


@router.put("/order", response_model=list[ApplicationOut])
def reorder_column(payload: ApplicationOrder, user: AuthenticatedUser, db: Db):
    """칸반 한 열의 새 순서(드래그 결과). 남의 기록·없는 id가 섞이면 404로 전체 거부."""
    try:
        rows = service.reorder(db, owner_id=user.sub, status=payload.status.value, ids=payload.ids)
    except service.ApplicationNotFound:
        raise _NOT_FOUND from None
    db.flush()
    today = date.today()
    return [_to_out(app, None, today) for app in rows]


@router.patch("/{app_id}", response_model=ApplicationOut)
def update_status(app_id: uuid.UUID, payload: ApplicationStatusUpdate, user: AuthenticatedUser, db: Db):
    try:
        app = service.update_status(db, app_id=app_id, owner_id=user.sub, status=payload.status.value)
    except service.ApplicationNotFound:
        raise _NOT_FOUND from None
    db.flush()
    return _to_out(app, None, date.today())


@router.delete("/{app_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_application(app_id: uuid.UUID, user: AuthenticatedUser, db: Db):
    try:
        service.delete_application(db, app_id=app_id, owner_id=user.sub)
    except service.ApplicationNotFound:
        raise _NOT_FOUND from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
