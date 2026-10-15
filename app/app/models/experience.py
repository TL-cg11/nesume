"""경험 데이터 (spec 3.5)."""
from datetime import date

from sqlalchemy import Date, Index, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._common import CreatedAt, DeletedAt, UpdatedAt, UuidPk, one_of, owner_fk

EXPERIENCE_TYPES = ("project", "activity", "award", "career", "education", "other")


class Experience(Base):
    __tablename__ = "experiences"
    __table_args__ = (
        one_of("type", EXPERIENCE_TYPES, "type"),
        Index("ix_experiences_tags", "tags", postgresql_using="gin"),
    )

    id: Mapped[UuidPk]
    owner_id: Mapped[str] = owner_fk()
    title: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(20))
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    role: Mapped[str | None] = mapped_column(String(200))
    tech_stack: Mapped[list[str]] = mapped_column(ARRAY(String(50)), default=list, server_default="{}")
    # v0는 평문. B7에서 암호화 컬럼으로 전환한다.
    outcome: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(50)), default=list, server_default="{}")
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]
    deleted_at: Mapped[DeletedAt]
