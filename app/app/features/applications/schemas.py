"""C15 — 지원 현황 API 스키마 (spec 4.5).

등급·owner_id는 요청으로 받지 않는다(서버가 토큰 `sub`·personal로 고정). status는 모델 CHECK와
동일한 5단계만 허용(`ApplicationStatus`). 응답엔 공고 요약(`posting`)과 남은 일수(`days_until`)를
얹어 칸반·마감 임박 화면이 추가 조회 없이 그린다.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.models.application import APPLICATION_STATUSES

#: 지원 상태 5단계(모델 one_of CHECK와 동일). enum이라 OpenAPI 문서·검증에 그대로 노출.
ApplicationStatus = Enum("ApplicationStatus", {s: s for s in APPLICATION_STATUSES}, type=str)


class ApplicationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: ApplicationStatus
    job_posting_id: uuid.UUID | None = None
    resume_id: uuid.UUID | None = None
    version_ids: list[uuid.UUID] = Field(default_factory=list)
    applied_at: date | None = None
    memo: str | None = None


class ApplicationStatusUpdate(BaseModel):
    """칸반 이동 — 상태만 바꾼다."""

    model_config = ConfigDict(extra="forbid")
    status: ApplicationStatus


class PostingBrief(BaseModel):
    """지원 기록에 딸린 공고 요약. 공고가 비활성/부재여도 기록은 보여야 하므로 목록에선 선택(nullable)."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    company_name: str | None
    title: str | None
    region_name: str | None
    closes_on: date | None
    is_active: bool


class ApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    status: str
    job_posting_id: uuid.UUID | None
    resume_id: uuid.UUID | None
    version_ids: list[uuid.UUID]
    applied_at: date | None
    memo: str | None
    created_at: datetime
    updated_at: datetime
    #: 딸린 공고 요약(없으면 null). days_until = 마감까지 남은 일수(상시·마감없음은 null).
    posting: PostingBrief | None = None
    days_until: int | None = None


class StatusCounts(BaseModel):
    """상태별 건수(칸반 집계). 5단계 전부 키로 존재(0 포함)."""

    model_config = ConfigDict(extra="forbid")
    applied: int = 0
    document_passed: int = 0
    interview: int = 0
    final: int = 0
    rejected: int = 0
