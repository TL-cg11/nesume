"""경험 데이터 (spec 3.5)."""
import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._common import CreatedAt, DeletedAt, Grade, grade_check, grade_column, owner_fk, UpdatedAt, UuidPk


class Experience(Base):
    __tablename__ = "experiences"
    __table_args__ = (
        grade_check(),
        Index("ix_experiences_tags", "tags", postgresql_using="gin"),
    )

    id: Mapped[UuidPk]
    owner_id: Mapped[str] = owner_fk()
    title: Mapped[str] = mapped_column(String(200))
    # 유형 값 목록은 문서에 예시(프로젝트·활동·수상 등)만 있어 제약 없이 둔다(팀 확정 후 CHECK 추가)
    type: Mapped[str] = mapped_column(String(20))
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    role: Mapped[str | None] = mapped_column(String(200))
    tech_stack: Mapped[list[str]] = mapped_column(ARRAY(String(50)), default=list, server_default="{}")
    # 문자열 필드는 PII 토큰화 상태로 저장한다(part2_guide 4.6, 4.8). 원문 PII는 B7 매핑 테이블에만.
    outcome: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[str | None] = mapped_column(Text)
    grade: Mapped[str] = grade_column(Grade.PERSONAL)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(50)), default=list, server_default="{}")
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]
    deleted_at: Mapped[DeletedAt]


class QuestionExperience(Base):
    """자소서 문항에 끌어온 경험 기록(B5 "자소서 문항에 끌어오기", part2_guide 4.18)."""

    __tablename__ = "question_experiences"

    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True
    )
    experience_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("experiences.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    owner_id: Mapped[str] = owner_fk()
    created_at: Mapped[CreatedAt]
