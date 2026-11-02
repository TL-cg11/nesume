"""면접 예상 질문·답변 연습 (tasks B13, spec 3.3, part2_guide 5.9·4.71).

- 질문은 자소서 하나에서 만든다. 만들 때 쓴 문항별 버전을 version_ids로 남긴다(FK 없음, shares와 같은 방식)
- 질문·답변·피드백은 B4·B7과 같이 PII 토큰화 상태로 저장하고 원문은 대응표에만 둔다
  (guide 초안의 *_enc 컬럼은 B7 결정(4.6·4.8)에 따라 토큰화 + vault_id로 대신한다)
- 연습 기록은 개인 등급이며 멘토 공유 범위에 들어가지 않는다(spec 3.7, 공유는 자소서 본문만)
- 자소서·계정 삭제 시 CASCADE. 대응표는 B20 물리 삭제에서 함께 정리한다
"""
import uuid

from sqlalchemy import ARRAY, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._common import CreatedAt, Grade, UuidPk, grade_check, grade_column, one_of, owner_fk

INTERVIEW_TYPES = ("personality", "job", "experience")  # 인성 / 직무 / 경험 검증


class InterviewQuestion(Base):
    __tablename__ = "interview_questions"
    __table_args__ = (grade_check(), one_of("type", INTERVIEW_TYPES, "type"))

    id: Mapped[UuidPk]
    owner_id: Mapped[str] = owner_fk()
    resume_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resumes.id", ondelete="CASCADE"), index=True)
    version_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid), default=list, server_default="{}")
    type: Mapped[str] = mapped_column(String(20))
    body: Mapped[str] = mapped_column(Text)  # PII 토큰화 상태
    vault_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("pii_vaults.id"))
    grade: Mapped[str] = grade_column(Grade.PERSONAL)
    created_at: Mapped[CreatedAt]


class PracticeAnswer(Base):
    __tablename__ = "practice_answers"
    __table_args__ = (grade_check(),)

    id: Mapped[UuidPk]
    owner_id: Mapped[str] = owner_fk()
    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interview_questions.id", ondelete="CASCADE"), index=True
    )
    answer: Mapped[str] = mapped_column(Text)  # PII 토큰화 상태
    # "구조: …\n구체성: …\n일관성: …\n제안: …". 모델을 못 불렀으면 NULL(답변만 기록)
    feedback: Mapped[str | None] = mapped_column(Text)
    vault_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("pii_vaults.id"))  # 답변·피드백 공용
    grade: Mapped[str] = grade_column(Grade.PERSONAL)
    created_at: Mapped[CreatedAt]
