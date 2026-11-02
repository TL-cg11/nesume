"""모의 면접(대화형) (tasks B13, spec 3.3, part2_guide 4.72 — 11/2 사용자 결정으로 대화형으로 대체).

- 면접 한 번 = interview_sessions 한 행. 자소서 하나로 시작하고,
  쓴 문항별 버전을 version_ids로 남긴다(FK 없음)
- 면접관 페르소나는 시작할 때 무작위로 정하고 그 면접 동안 바꾸지 않는다(사용자 선택 없음)
- 진행: 주 질문 main_count개, 주 질문마다 꼬리 질문 최대 2개. 끝나면 종합 피드백 + 자소서 기반 예상 질문 목록
- 대화·피드백·예상 질문은 B4·B7과 같이 PII 토큰화 상태로 저장하고 원문은 대응표에만 둔다
- 연습 기록은 개인 등급이며 멘토 공유 범위에 들어가지 않는다(spec 3.7)
- 자소서·계정 삭제 시 CASCADE. 대응표는 B20 물리 삭제에서 함께 정리한다
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._common import CreatedAt, Grade, UuidPk, grade_check, grade_column, one_of, owner_fk

PERSONAS = ("practical", "personality", "pressure")  # 실무 / 인성 / 압박
SESSION_STATUSES = ("active", "finished")
MESSAGE_ROLES = ("interviewer", "candidate")
MESSAGE_KINDS = ("main", "follow_up", "closing")  # 면접관 메시지만. 지원자 답변은 NULL


class InterviewSession(Base):
    __tablename__ = "interview_sessions"
    __table_args__ = (
        grade_check(),
        one_of("persona", PERSONAS, "persona"),
        one_of("status", SESSION_STATUSES, "status"),
        CheckConstraint("main_count BETWEEN 1 AND 10", name="main_count_range"),
    )

    id: Mapped[UuidPk]
    owner_id: Mapped[str] = owner_fk()
    resume_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resumes.id", ondelete="CASCADE"), index=True)
    version_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid), default=list, server_default="{}")
    persona: Mapped[str] = mapped_column(String(20))
    main_count: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10), default="active", server_default="active")
    # 종료 후 채움. 모델을 못 불렀으면 NULL(다시 받기 가능). 둘 다 PII 토큰화 상태, 대응표 공용
    feedback: Mapped[str | None] = mapped_column(Text)
    expected_questions: Mapped[str | None] = mapped_column(Text)  # 한 줄에 하나
    vault_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("pii_vaults.id"))
    grade: Mapped[str] = grade_column(Grade.PERSONAL)
    created_at: Mapped[CreatedAt]
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InterviewMessage(Base):
    __tablename__ = "interview_messages"
    __table_args__ = (
        grade_check(),
        UniqueConstraint("session_id", "seq"),
        one_of("role", MESSAGE_ROLES, "role"),
        CheckConstraint("kind IS NULL OR kind IN ('main', 'follow_up', 'closing')", name="kind"),
    )

    id: Mapped[UuidPk]
    owner_id: Mapped[str] = owner_fk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interview_sessions.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)  # 0부터, 대화 순서
    role: Mapped[str] = mapped_column(String(12))
    kind: Mapped[str | None] = mapped_column(String(10))
    body: Mapped[str] = mapped_column(Text)  # PII 토큰화 상태
    vault_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("pii_vaults.id"))
    grade: Mapped[str] = grade_column(Grade.PERSONAL)
    created_at: Mapped[CreatedAt]
