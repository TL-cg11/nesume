"""자소서 → 문항 → 버전 (spec 3.1), 자소서 스냅샷 (part2_guide 4.10).

- 버전은 INSERT 전용이다. UPDATE는 DB 트리거로 거부한다(마이그레이션 0002).
- 스냅샷은 문항별 버전 묶음이며, 지원 기록·PDF가 참조하는 "자소서 버전" 단위다.
  스냅샷이 참조하는 버전은 단독 삭제(압축)할 수 없다(FK NO ACTION).
"""
import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models._common import CreatedAt, DeletedAt, Grade, grade_check, grade_column, one_of, owner_fk, UpdatedAt, UuidPk

RESUME_STATUSES = ("draft", "final")
VERSION_SOURCES = ("manual", "ai")


class Resume(Base):
    __tablename__ = "resumes"
    __table_args__ = (one_of("status", RESUME_STATUSES, "status"), grade_check())

    id: Mapped[UuidPk]
    owner_id: Mapped[str] = owner_fk()
    title: Mapped[str] = mapped_column(String(200))
    # 공고 내부 고유 ID(C4). 공고 테이블은 C 소유라 FK는 C4 마이그레이션에서 추가한다.
    job_posting_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(20), default="draft", server_default="draft")
    grade: Mapped[str] = grade_column(Grade.PERSONAL)
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
    # v0는 평문. B7에서 사용자별 DEK 암호화 컬럼으로 전환한다.
    body: Mapped[str] = mapped_column(Text)
    char_count: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(10))
    # 50개 초과 시 압축된 보관 요약 행 여부(spec 3.1)
    compressed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    grade: Mapped[str] = grade_column(Grade.PERSONAL)
    created_at: Mapped[CreatedAt]

    question: Mapped[Question] = relationship(back_populates="versions")


class ResumeSnapshot(Base):
    __tablename__ = "resume_snapshots"

    id: Mapped[UuidPk]
    resume_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resumes.id", ondelete="CASCADE"), index=True
    )
    owner_id: Mapped[str] = owner_fk()
    created_at: Mapped[CreatedAt]

    items: Mapped[list["SnapshotItem"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True
    )


class SnapshotItem(Base):
    __tablename__ = "snapshot_items"

    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("resume_snapshots.id", ondelete="CASCADE"), primary_key=True
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), primary_key=True
    )
    # NO ACTION: 참조 중인 버전의 단독 삭제(압축)는 거부, 자소서 삭제 연쇄는 같은 문장 안에서 허용
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("versions.id"), index=True)

