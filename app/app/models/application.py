"""지원 기록 기본 테이블 (spec 4.5). 기능 구현은 C15 소유."""
import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, String, Text, Uuid
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._common import CreatedAt, Grade, grade_check, grade_column, one_of, owner_fk, UpdatedAt, UuidPk

APPLICATION_STATUSES = ("applied", "document_passed", "interview", "final", "rejected")


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (one_of("status", APPLICATION_STATUSES, "status"), grade_check())

    id: Mapped[UuidPk]
    owner_id: Mapped[str] = owner_fk()
    # 공고 내부 고유 ID(C4). 참조 중인 공고는 물리 삭제 금지(RESTRICT, C 결정 2·part2_guide 4.30)
    job_posting_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("job_postings.id", ondelete="RESTRICT"), index=True
    )
    resume_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("resumes.id", ondelete="SET NULL"))
    # 지원 시점의 문항별 버전 ID 고정 참조(spec 4.5 "자소서 ID·버전"). FK 없음 → 압축 제외는 B4 서비스 로직
    version_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid), default=list, server_default="{}")
    applied_at: Mapped[date | None] = mapped_column(Date)
    # 값 목록은 spec 4.5. 기본값은 문서에 없어 두지 않는다(생성 시 지정)
    status: Mapped[str] = mapped_column(String(20))
    memo: Mapped[str | None] = mapped_column(Text)
    grade: Mapped[str] = grade_column(Grade.PERSONAL)
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]
