"""지원 기록 기본 테이블 (spec 4.5). 기능 구현은 C15 소유."""
import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._common import CreatedAt, Grade, grade_check, grade_column, one_of, owner_fk, UpdatedAt, UuidPk

APPLICATION_STATUSES = ("applied", "document_passed", "interview", "final", "rejected")


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (one_of("status", APPLICATION_STATUSES, "status"), grade_check())

    id: Mapped[UuidPk]
    owner_id: Mapped[str] = owner_fk()
    # 공고 내부 고유 ID(C4). FK는 공고 테이블 생성 시 C가 추가한다.
    job_posting_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    resume_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("resumes.id", ondelete="SET NULL"))
    # 지원 시점의 자소서 버전 고정 참조(part2_guide 4.10)
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("resume_snapshots.id", ondelete="SET NULL")
    )
    applied_at: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="applied", server_default="applied")
    memo: Mapped[str | None] = mapped_column(Text)
    grade: Mapped[str] = grade_column(Grade.PERSONAL)
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]
