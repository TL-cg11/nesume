"""멘토 공유 입출력. 소유자·버전·만료 시각은 서버가 정한다."""
import uuid
from datetime import date, datetime

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# 작성자가 붙이는 멘토 별칭(4.43)
MentorLabel = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]


class ShareCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mentor_id: str = Field(min_length=1, max_length=128)
    mentor_label: MentorLabel
    end_date: date | None = None  # 비우면 공유일 포함 7일째 날
    confirm: bool = False         # 같은 멘토에게 유효한 공유가 있을 때 확인 후 true로 다시 요청


class ShareExtend(BaseModel):
    model_config = ConfigDict(extra="forbid")

    end_date: date


class ShareRename(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mentor_label: MentorLabel


class ShareOut(BaseModel):
    id: uuid.UUID
    resume_id: uuid.UUID
    mentor_id: str
    mentor_label: str
    end_date: date
    expires_at: datetime
    status: str  # active / expired / revoked
    created_at: datetime
    revoked_at: datetime | None
    comment_count: int = 0  # 멘토 코멘트 수(B17)
    unread_count: int = 0   # 작성자가 확인 안 한 코멘트 수


class ReceivedShare(BaseModel):
    id: uuid.UUID
    resume_title: str
    end_date: date


CommentBody = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class CommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: uuid.UUID
    paragraph_index: int = Field(ge=0)
    body: CommentBody


class CommentEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: CommentBody


class MentorComment(BaseModel):
    id: uuid.UUID
    version_id: uuid.UUID
    paragraph_index: int
    body: str  # 비공개 문구 표시
    created_at: datetime
    updated_at: datetime


class OwnerComment(BaseModel):
    id: uuid.UUID
    version_id: uuid.UUID
    question_title: str | None  # 공유 뒤 삭제된 문항이면 None
    paragraph_index: int
    paragraph: str | None       # 코멘트가 달린 문단(원문)
    body: str                   # 원문
    read_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SharedQuestion(BaseModel):
    question_title: str
    char_limit: int | None
    version_id: uuid.UUID
    version_no: int
    body: str  # PII는 '(전화번호 비공개)' 같은 문구로 표시(원문 복원은 소유자만, tasks B7, 4.44)
    paragraphs: list[str]  # 빈 줄 기준 문단(코멘트 위치, 4.47)
    comments: list[MentorComment]


class SharedResume(BaseModel):
    id: uuid.UUID
    resume_title: str
    end_date: date
    questions: list[SharedQuestion]
