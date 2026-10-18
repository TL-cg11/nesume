"""소유자 범위 조회 (part2_guide 5.7). owner_id·소프트 삭제 조건은 이 모듈에서만 붙인다."""
import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Experience, QuestionExperience


def get_experience(db: Session, owner_id: str, experience_id: uuid.UUID) -> Experience | None:
    return db.scalar(
        select(Experience).where(
            Experience.id == experience_id,
            Experience.owner_id == owner_id,
            Experience.deleted_at.is_(None),
        )
    )


def list_experiences(
    db: Session, owner_id: str, tags_any: Sequence[str], limit: int, offset: int
) -> Sequence[Experience]:
    stmt = select(Experience).where(Experience.owner_id == owner_id, Experience.deleted_at.is_(None))
    if tags_any:
        # 하나라도 포함(OR, part2_guide 4.21). GIN 인덱스 ix_experiences_tags 사용
        stmt = stmt.where(Experience.tags.overlap(list(tags_any)))
    return db.scalars(
        stmt.order_by(Experience.period_start.desc().nulls_last(), Experience.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()


def get_link(db: Session, owner_id: str, question_id: uuid.UUID, experience_id: uuid.UUID):
    return db.scalar(
        select(QuestionExperience).where(
            QuestionExperience.question_id == question_id,
            QuestionExperience.experience_id == experience_id,
            QuestionExperience.owner_id == owner_id,
        )
    )


def linked_experiences(db: Session, owner_id: str, question_id: uuid.UUID) -> Sequence[Experience]:
    return db.scalars(
        select(Experience)
        .join(QuestionExperience, QuestionExperience.experience_id == Experience.id)
        .where(
            QuestionExperience.question_id == question_id,
            QuestionExperience.owner_id == owner_id,
            Experience.deleted_at.is_(None),
        )
        .order_by(QuestionExperience.created_at)
    ).all()
