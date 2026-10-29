import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# 등급(grade)·owner_id는 요청으로 받지 않는다. 서버가 부여한다(spec 3.1, B8).

# 자소서 상태(발표 시안 기준, part2_guide 4.12·4.54). 비우면 '상태 없음'(대시보드에서는 작성 중으로 센다).
# DB 제약은 두지 않는다(기존 행 유지). 새로 저장할 때만 이 값을 받는다.
RESUME_STATUSES = ("작성 중", "검토 중", "완료")
ResumeStatus = Literal["작성 중", "검토 중", "완료"]


class ResumeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    job_posting_id: uuid.UUID | None = None
    status: ResumeStatus | None = None


class ResumeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=200)
    job_posting_id: uuid.UUID | None = None
    status: ResumeStatus | None = None


# 10/28 결정: 문항 제목 300자, 본문·글자수 설정 10,000자까지(화면 기본 글자수 1,000자)
QUESTION_TITLE_MAX = 300
BODY_MAX = 10_000


class QuestionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=QUESTION_TITLE_MAX)
    char_limit: int | None = Field(default=None, gt=0, le=BODY_MAX)
    position: int | None = Field(default=None, ge=0)


class QuestionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=QUESTION_TITLE_MAX)
    char_limit: int | None = Field(default=None, gt=0, le=BODY_MAX)
    position: int | None = Field(default=None, ge=0)


class VersionCreate(BaseModel):
    """사용자 직접 저장. 생성 방식은 manual로 고정(AI 버전은 A6이 서비스 함수로 저장)."""

    model_config = ConfigDict(extra="forbid")
    body: str = Field(max_length=BODY_MAX)


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


class DashboardRecent(BaseModel):
    id: uuid.UUID
    title: str
    status: str | None
    question_count: int
    last_edited_at: datetime  # 자소서 정보 수정과 버전 저장 중 늦은 쪽
    share_summary: ShareSummary | None = None


class DashboardLatestSave(BaseModel):
    resume_id: uuid.UUID
    resume_title: str
    question_title: str
    version_no: int
    created_at: datetime


class Dashboard(BaseModel):
    """홈 대시보드(사용자용, 발표 시안 화면 1, part2_guide 4.54)."""

    resume_total: int
    resume_in_progress: int     # '완료'가 아닌 자소서(상태 없음 포함)
    experience_total: int
    question_total: int
    question_filled: int        # 저장된 버전(본문)이 있는 문항
    progress_percent: int       # question_filled / question_total, 문항이 없으면 0
    latest_save: DashboardLatestSave | None
    recent: list[DashboardRecent]  # 최근 수정 4건
