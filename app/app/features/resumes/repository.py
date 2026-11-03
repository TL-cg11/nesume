"""소유자 범위 조회 (part2_guide 5.7).

모든 조회는 owner_id 조건과 소프트 삭제 제외 조건을 이 모듈에서 붙인다. 라우터·서비스에서
직접 쿼리하지 않는다. 다른 사용자의 리소스는 존재하지 않는 것과 같게(None) 반환한다.
"""
import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Experience, Question, Resume, Version


def get_resume(db: Session, owner_id: str, resume_id: uuid.UUID) -> Resume | None:
    return db.scalar(
        select(Resume).where(
            Resume.id == resume_id, Resume.owner_id == owner_id, Resume.deleted_at.is_(None)
        )
    )


def list_resumes(db: Session, owner_id: str, limit: int, offset: int) -> Sequence[Resume]:
    return db.scalars(
        select(Resume)
        .where(Resume.owner_id == owner_id, Resume.deleted_at.is_(None))
        .order_by(Resume.updated_at.desc(), Resume.id)
        .limit(limit)
        .offset(offset)
    ).all()


def get_question(
    db: Session, owner_id: str, resume_id: uuid.UUID, question_id: uuid.UUID, *, for_update: bool = False
) -> Question | None:
    stmt = (
        select(Question)
        .join(Resume, Resume.id == Question.resume_id)
        .where(
            Question.id == question_id,
            Question.resume_id == resume_id,
            Question.owner_id == owner_id,
            Question.deleted_at.is_(None),
            Resume.deleted_at.is_(None),
        )
    )
    if for_update:
        # 버전 번호 부여 시 동시 저장 경합 방지
        stmt = stmt.with_for_update(of=Question)
    return db.scalar(stmt)


def list_questions(db: Session, owner_id: str, resume_id: uuid.UUID) -> Sequence[Question]:
    return db.scalars(
        select(Question)
        .where(
            Question.resume_id == resume_id,
            Question.owner_id == owner_id,
            Question.deleted_at.is_(None),
        )
        .order_by(Question.position, Question.id)
    ).all()


def latest_versions(db: Session, question_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Version]:
    if not question_ids:
        return {}
    rows = db.scalars(
        select(Version)
        .where(Version.question_id.in_(question_ids))
        .distinct(Version.question_id)
        .order_by(Version.question_id, Version.version_no.desc())
    ).all()
    return {v.question_id: v for v in rows}


def list_versions(db: Session, owner_id: str, question_id: uuid.UUID) -> Sequence[Version]:
    return db.scalars(
        select(Version)
        .where(Version.question_id == question_id, Version.owner_id == owner_id)
        .order_by(Version.version_no.desc())
    ).all()


def get_version_any_question(db: Session, owner_id: str, version_id: uuid.UUID) -> Version | None:
    """본인 버전(문항 무관). 멘토 공유에서 고른 버전을 확인할 때(B10, 10/29)."""
    return db.scalar(select(Version).where(Version.id == version_id, Version.owner_id == owner_id))


def get_version(
    db: Session, owner_id: str, question_id: uuid.UUID, version_id: uuid.UUID
) -> Version | None:
    return db.scalar(
        select(Version).where(
            Version.id == version_id,
            Version.question_id == question_id,
            Version.owner_id == owner_id,
        )
    )


def get_version_by_no(
    db: Session, owner_id: str, question_id: uuid.UUID, version_no: int
) -> Version | None:
    return db.scalar(
        select(Version).where(
            Version.question_id == question_id,
            Version.owner_id == owner_id,
            Version.version_no == version_no,
        )
    )


def max_version_no(db: Session, question_id: uuid.UUID) -> int:
    return db.scalar(
        select(func.coalesce(func.max(Version.version_no), 0)).where(Version.question_id == question_id)
    )


def count_versions(db: Session, question_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).where(Version.question_id == question_id))


def dashboard_counts(db: Session, owner_id: str):
    """대시보드 집계 재료. 삭제된 자소서·문항은 제외."""
    resumes = db.scalars(select(Resume).where(Resume.owner_id == owner_id, Resume.deleted_at.is_(None))).all()
    questions = db.scalars(
        select(Question).join(Resume, Resume.id == Question.resume_id)
        .where(Question.owner_id == owner_id, Question.deleted_at.is_(None), Resume.deleted_at.is_(None))
    ).all()
    experience_total = db.scalar(select(func.count()).select_from(Experience)
                                 .where(Experience.owner_id == owner_id, Experience.deleted_at.is_(None)))
    return resumes, questions, experience_total


def count_resumes(db: Session, owner_id: str) -> int:
    return db.scalar(select(func.count()).select_from(Resume)
                     .where(Resume.owner_id == owner_id, Resume.deleted_at.is_(None))) or 0


def version_used_by_application(db: Session, owner_id: str, version_id: uuid.UUID) -> bool:
    from app.models import Application

    return db.scalar(select(Application.id).where(Application.owner_id == owner_id,
                                                  Application.version_ids.any(version_id)).limit(1)) is not None


def version_used_by_active_share(db: Session, owner_id: str, version_id: uuid.UUID) -> bool:
    from datetime import UTC, datetime

    from app.models import Share

    return db.scalar(select(Share.id).where(
        Share.owner_id == owner_id, Share.version_ids.any(version_id), Share.revoked_at.is_(None),
        Share.expires_at > datetime.now(UTC)).limit(1)) is not None
