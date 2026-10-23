"""C14 — 학습 로드맵 API 스키마.

owner_id·grade는 요청으로 받지 않는다(서버가 토큰 `sub`·personal로 고정). 갭은 호출측이 넘긴다
(A11 대조 → C10 정리 결과) — 갭은 본인 로드맵 콘텐츠만 좌우하므로 보안 경계가 아니다(C8 held_keys와 같은 결).
사용자 추가 항목의 URL은 **http/https만**(javascript:·data: 차단) — 개인·미검증·공유 제외.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.features.skill_gap.gap import IMPORTANCE_RANK, LearningGap
from app.models.learning import ITEM_STATUSES, LEARNING_MODES

Importance = Enum("Importance", {k: k for k in IMPORTANCE_RANK}, type=str)
ItemStatus = Enum("ItemStatus", {s: s for s in ITEM_STATUSES}, type=str)
LearningMode = Enum("LearningMode", {m: m for m in LEARNING_MODES}, type=str)

_SAFE_URL_PREFIXES = ("http://", "https://")


def _validate_url(v: str | None) -> str | None:
    """개인 항목 URL 안전장치: http/https만(javascript:·data:·상대경로 차단)."""
    if v is None:
        return None
    v = v.strip()
    if not v:
        return None
    if not v.lower().startswith(_SAFE_URL_PREFIXES):
        raise ValueError("url은 http(s)만 허용됩니다")
    return v


class GapIn(BaseModel):
    """배워야 할 역량 1건(A11 대조 → C10 결과). 서버가 콘텐츠를 붙여 배치한다."""

    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=200)
    importance: Importance = Importance.required  # type: ignore[attr-defined]
    evidence_fields: list[str] = Field(default_factory=list)

    def to_gap(self) -> LearningGap:
        return LearningGap(
            key=self.key,
            label=self.label,
            importance=self.importance.value,
            evidence_fields=tuple(self.evidence_fields),
        )


class RoadmapCreate(BaseModel):
    """로드맵 생성 요청. 갭 + 주당 시간 + 모드 → 서버가 콘텐츠 매칭·주차 배치·저장."""

    model_config = ConfigDict(extra="forbid")
    gaps: list[GapIn] = Field(min_length=1, max_length=100)
    job_posting_id: uuid.UUID | None = None
    weekly_hours: int = Field(default=5, ge=1, le=60)
    mode: LearningMode | None = None
    max_weeks: int | None = Field(default=None, ge=1, le=52)


class RoadmapUpdate(BaseModel):
    """로드맵 수정 — 주당 시간만(재배치는 재생성/항목 이동으로)."""

    model_config = ConfigDict(extra="forbid")
    weekly_hours: int = Field(ge=1, le=60)


class UserItemCreate(BaseModel):
    """사용자가 직접 넣는 항목(origin=user). 개인·미검증 — 공유 뷰 제외."""

    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    url: str | None = None
    hours: float | None = Field(default=None, ge=0, le=1000)
    week: int | None = Field(default=None, ge=1, le=52)

    _check_url = field_validator("url")(_validate_url)


class ItemUpdate(BaseModel):
    """항목 수정 — 완료 체크(status)·주차 이동(week)·순서(position). 준 필드만 바뀐다."""

    model_config = ConfigDict(extra="forbid")
    status: ItemStatus | None = None
    week: int | None = Field(default=None, ge=1, le=52)
    position: int | None = Field(default=None, ge=0)


class RoadmapItemOut(BaseModel):
    """로드맵 항목 1건(표시용). 시스템 항목은 콘텐츠에서, 사용자 항목은 inline에서 값을 채운다."""

    model_config = ConfigDict(extra="forbid")
    id: uuid.UUID
    origin: str
    status: str
    week: int | None
    position: int
    #: 미검증 외부 링크 여부(사용자 항목이고 url이 있으면 True) — 공유/표시에서 구분.
    unverified: bool = False
    title: str | None = None
    url: str | None = None
    hours: float | None = None
    source: str | None = None     # 시스템 항목 콘텐츠 출처(kmooc 등)
    provider: str | None = None
    certificate: bool | None = None


class RoadmapOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    job_posting_id: uuid.UUID | None
    weekly_hours: int
    grade: str
    #: "왜 이 순서인지" LLM 설명(A8 경유). 아직 생성 안 했으면 null.
    explanation: str | None = None
    created_at: datetime
    updated_at: datetime
    items: list[RoadmapItemOut] = Field(default_factory=list)


__all__ = [
    "GapIn",
    "ItemStatus",
    "ItemUpdate",
    "RoadmapCreate",
    "RoadmapItemOut",
    "RoadmapOut",
    "RoadmapUpdate",
    "UserItemCreate",
]
