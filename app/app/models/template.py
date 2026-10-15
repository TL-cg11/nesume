"""프롬프트 템플릿 (spec 3.6). 내부 등급, 운영자만 수정. 수정은 새 버전 생성."""
from typing import Any

from sqlalchemy import Boolean, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._common import CreatedAt, Grade, grade_check, grade_column, UserId, UuidPk


class PromptTemplate(Base):
    __tablename__ = "templates"
    __table_args__ = (
        UniqueConstraint("name", "version"),
        grade_check(),
        # 이름별 활성 버전은 최대 1개
        Index("uq_templates_active_name", "name", unique=True, postgresql_where=text("is_active")),
    )

    id: Mapped[UuidPk]
    name: Mapped[str] = mapped_column(String(100))
    purpose: Mapped[str] = mapped_column(String(50))  # rewrite, star, keyword, interview, github 등
    body: Mapped[str] = mapped_column(Text)
    variables: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default="[]")
    version: Mapped[int] = mapped_column(Integer)
    grade: Mapped[str] = grade_column(Grade.INTERNAL)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # 운영자 계정이 삭제돼도 이력은 남긴다(FK 없음)
    created_by: Mapped[UserId]
    created_at: Mapped[CreatedAt]
