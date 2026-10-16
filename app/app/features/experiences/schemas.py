import uuid
from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

# 등급·owner_id는 요청으로 받지 않는다(B8). 필드는 spec 3.5.
Item = Annotated[str, Field(min_length=1, max_length=50)]  # 사용 기술·태그 항목(DB String(50))


class ExperienceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    type: str = Field(min_length=1, max_length=20)
    period_start: date | None = None
    period_end: date | None = None
    role: str | None = Field(default=None, max_length=200)
    tech_stack: list[Item] = Field(default_factory=list)
    outcome: str | None = None
    detail: str | None = None
    tags: list[Item] = Field(default_factory=list)


class ExperienceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=200)
    type: str | None = Field(default=None, min_length=1, max_length=20)
    period_start: date | None = None
    period_end: date | None = None
    role: str | None = Field(default=None, max_length=200)
    tech_stack: list[Item] | None = None
    outcome: str | None = None
    detail: str | None = None
    tags: list[Item] | None = None


class ExperienceOut(BaseModel):
    id: uuid.UUID
    title: str
    type: str
    period_start: date | None
    period_end: date | None
    role: str | None
    tech_stack: list[str]
    outcome: str | None
    detail: str | None
    tags: list[str]
    created_at: datetime
    updated_at: datetime


class LinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    experience_id: uuid.UUID
