"""자소서 → 문항 → 버전 (spec 3.1).

- 버전은 INSERT 전용이다. UPDATE는 DB 트리거로 거부한다(마이그레이션 0002).
- 지원 기록은 문항별 버전 ID 배열(applications.version_ids)로 버전을 고정 참조한다.
  배열은 FK로 보호되지 않으므로, 압축 시 참조 중인 버전 제외는 B4 서비스 로직에서 처리한다.
"""
import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models._common import CreatedAt, DeletedAt, Grade, grade_check, grade_column, one_of, owner_fk, UpdatedAt, UuidPk

VERSION_SOURCES = ("manual", "ai")


class Resume(Base):
    __tablename__ = "resumes"
    __table_args__ = (
        grade_check(),
        CheckConstraint("jsonb_typeof(shared_with) = 'array'", name="shared_with_array"),
    )

    id: Mapped[UuidPk]
    owner_id: Mapped[str] = owner_fk()
    title: Mapped[str] = mapped_column(String(200))
    # 공고 내부 고유 ID(C4). 참조 중인 공고는 물리 삭제 금지(RESTRICT, C 결정 2·part2_guide 4.30)
    job_posting_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("job_postings.id", ondelete="RESTRICT")
    )
    # 상태 값 목록은 문서에 정의되지 않아 제약 없이 둔다(팀 확정 후 CHECK 추가)
    status: Mapped[str | None] = mapped_column(String(20))
    grade: Mapped[str] = grade_column(Grade.PERSONAL)
    # B2: 공유 대상과 멘토별 만료 [{"user_id": str, "expires_at": ISO8601}]. 원본은 shares, B10에서 동기화
    shared_with: Mapped[list[dict]] = mapped_column(JSONB, default=list, server_default="[]")
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]
    deleted_at: Mapped[DeletedAt]

    questions: Mapped[list["Question"]] = relationship(
        back_populates="resume", cascade="all, delete-orphan", passive_deletes=True,
        order_by="Question.position",
    )


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (grade_check(),)

    id: Mapped[UuidPk]
    resume_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resumes.id", ondelete="CASCADE"), index=True
    )
    owner_id: Mapped[str] = owner_fk()
    title: Mapped[str] = mapped_column(Text)
    char_limit: Mapped[int | None] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    grade: Mapped[str] = grade_column(Grade.PERSONAL)
    deleted_at: Mapped[DeletedAt]

    resume: Mapped[Resume] = relationship(back_populates="questions")
    versions: Mapped[list["Version"]] = relationship(
        back_populates="question", passive_deletes=True, order_by="Version.version_no"
    )


class Version(Base):
    __tablename__ = "versions"
    __table_args__ = (
        UniqueConstraint("question_id", "version_no"),
        one_of("source", VERSION_SOURCES, "source"),
        grade_check(),
    )

    id: Mapped[UuidPk]
    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), index=True
    )
    owner_id: Mapped[str] = owner_fk()
    version_no: Mapped[int] = mapped_column(Integer)
    # PII 토큰화 상태로 저장한다(part2_guide 4.8). 원문 PII는 B7 매핑 테이블에만.
    body: Mapped[str] = mapped_column(Text)
    char_count: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(10))
    # 50개 초과 시 압축된 보관 요약 행 여부(spec 3.1)
    compressed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # 이전 버전 복원으로 만들어진 경우 원본 버전 ID(B4). versions는 UPDATE 금지 트리거가 있어
    # ON DELETE SET NULL 같은 FK 연쇄 수정이 불가하므로 FK 없이 둔다.
    restored_from: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    grade: Mapped[str] = grade_column(Grade.PERSONAL)
    created_at: Mapped[CreatedAt]

    question: Mapped[Question] = relationship(back_populates="versions")
