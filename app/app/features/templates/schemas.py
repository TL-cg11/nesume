"""프롬프트 템플릿 입출력. 버전·활성 여부·작성자·등급은 서버가 정한다."""
import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Name = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_.-]{0,99}$")]
Purpose = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
Body = Annotated[str, StringConstraints(min_length=1, max_length=20000)]
VarName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,49}$")]


class TemplateCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    purpose: Purpose  # rewrite, star, keyword, interview, github 등
    body: Body
    variables: list[VarName] = Field(default_factory=list, max_length=30)


class TemplateNewVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: Body
    variables: list[VarName] = Field(default_factory=list, max_length=30)
    purpose: Purpose | None = None


class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    purpose: str
    body: str
    variables: list[str]
    version: int
    is_active: bool
    created_by: str
    created_at: datetime


class TemplateSummary(BaseModel):
    name: str
    purpose: str
    latest_version: int
    active_version: int | None
