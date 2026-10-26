import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# 등급(grade)·owner_id는 요청으로 받지 않는다. 서버가 부여한다(spec 3.1, B8).


class ResumeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    job_posting_id: uuid.UUID | None = None
    status: str | None = Field(default=None, max_length=20)


class ResumeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=200)
    job_posting_id: uuid.UUID | None = None
    status: str | None = Field(default=None, max_length=20)


class QuestionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1)
    char_limit: int | None = Field(default=None, gt=0)
    position: int | None = Field(default=None, ge=0)


class QuestionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1)
    char_limit: int | None = Field(default=None, gt=0)
    position: int | None = Field(default=None, ge=0)


class VersionCreate(BaseModel):
    """사용자 직접 저장. 생성 방식은 manual로 고정(AI 버전은 A6이 서비스 함수로 저장)."""

    model_config = ConfigDict(extra="forbid")
    body: str


class VersionShareTag(BaseModel):
    """이 버전을 고정한 멘토 공유(B10, 작성자 화면용, 4.43)."""

    share_id: uuid.UUID
    mentor_label: str
    end_date: date
    status: str  # active / expired / revoked
    ended_on: date | None  # 만료일 또는 취소일(KST). 유효하면 None


class ShareSummary(BaseModel):
    """자소서의 유효한 멘토 공유 요약."""

    active_count: int
    earliest_end_date: date


class VersionSummary(BaseModel):
    """타임라인 항목. 본문은 포함하지 않는다."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    version_no: int
    source: str
    char_count: int
    compressed: bool
    restored_from: uuid.UUID | None
    created_at: datetime
    shares: list[VersionShareTag] = []


class VersionOut(VersionSummary):
    body: str


class VersionCreated(VersionOut):
    # 문항당 50개 초과 여부(spec 3.1). 압축 방식은 팀 확인 후 구현(part2_guide 4.14)
    over_limit: bool


class QuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str
    char_limit: int | None
    position: int
    latest_version: VersionSummary | None = None


class ResumeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str
    job_posting_id: uuid.UUID | None
    status: str | None
    created_at: datetime
    updated_at: datetime
    share_summary: ShareSummary | None = None


class ResumeDetail(ResumeOut):
    questions: list[QuestionOut]


class DiffSegment(BaseModel):
    op: Literal["equal", "insert", "delete", "replace"]
    before: str
    after: str


class VersionDiff(BaseModel):
    from_version: int
    to_version: int
    segments: list[DiffSegment]
