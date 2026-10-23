"""멘토 공유 입출력. 소유자·버전·만료 시각은 서버가 정한다."""
import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class ShareCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mentor_id: str = Field(min_length=1, max_length=128)
    end_date: date | None = None  # 비우면 공유일 포함 7일째 날
    confirm: bool = False         # 같은 멘토에게 유효한 공유가 있을 때 확인 후 true로 다시 요청


class ShareExtend(BaseModel):
    model_config = ConfigDict(extra="forbid")

    end_date: date


class ShareOut(BaseModel):
    id: uuid.UUID
    resume_id: uuid.UUID
    mentor_id: str
    end_date: date
    expires_at: datetime
    status: str  # active / expired / revoked
    created_at: datetime
    revoked_at: datetime | None


class ReceivedShare(BaseModel):
    id: uuid.UUID
    resume_title: str
    end_date: date


class SharedQuestion(BaseModel):
    question_title: str
    char_limit: int | None
    version_no: int
    body: str  # PII 토큰 상태 그대로(원문 복원은 소유자만, tasks B7)


class SharedResume(BaseModel):
    id: uuid.UUID
    resume_title: str
    end_date: date
    questions: list[SharedQuestion]
