"""공유 조회 (part2_guide 5.7). 소유자·공유 대상·유효 조건은 이 모듈에서만 붙인다."""
import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Question, Resume, Share, User, Version


def lock_resume(db: Session, owner_id: str, resume_id: uuid.UUID) -> Resume | None:
    """공유 생성 동안 같은 자소서에 대한 동시 공유를 직렬화한다."""
    return db.scalar(
        select(Resume)
        .where(Resume.id == resume_id, Resume.owner_id == owner_id, Resume.deleted_at.is_(None))
        .with_for_update()
    )


def get_user(db: Session, user_id: str) -> User | None:
    return db.get(User, user_id)


def _active(now: datetime):
    return (Share.revoked_at.is_(None), Share.expires_at > now)


def active_for_mentor(db: Session, owner_id: str, mentor_id: str, now: datetime) -> Sequence[Share]:
    return db.scalars(
        select(Share)
        .join(Resume, Resume.id == Share.resume_id)
        .where(Share.owner_id == owner_id, Share.shared_with == mentor_id, *_active(now),
               Resume.deleted_at.is_(None))
        .order_by(Share.created_at)
    ).all()


def active_for_resume(db: Session, resume_id: uuid.UUID, now: datetime) -> Sequence[Share]:
    return db.scalars(
        select(Share).where(Share.resume_id == resume_id, *_active(now)).order_by(Share.shared_with)
    ).all()


def list_for_owner(db: Session, owner_id: str, resume_id: uuid.UUID) -> Sequence[Share]:
    return db.scalars(
        select(Share)
        .where(Share.owner_id == owner_id, Share.resume_id == resume_id)
        .order_by(Share.created_at.desc())
    ).all()


def get_for_owner(db: Session, owner_id: str, share_id: uuid.UUID) -> Share | None:
    return db.scalar(
        select(Share)
        .join(Resume, Resume.id == Share.resume_id)
        .where(Share.id == share_id, Share.owner_id == owner_id, Resume.deleted_at.is_(None))
        .with_for_update(of=Share)
    )


def list_for_mentor(db: Session, mentor_id: str, now: datetime) -> Sequence[tuple[Share, str]]:
    return db.execute(
        select(Share, Resume.title)
        .join(Resume, Resume.id == Share.resume_id)
        .where(Share.shared_with == mentor_id, *_active(now), Resume.deleted_at.is_(None))
        .order_by(Share.expires_at)
    ).all()


def get_for_mentor(db: Session, mentor_id: str, share_id: uuid.UUID, now: datetime):
    return db.execute(
        select(Share, Resume)
        .join(Resume, Resume.id == Share.resume_id)
        .where(Share.id == share_id, Share.shared_with == mentor_id, *_active(now),
               Resume.deleted_at.is_(None))
    ).first()


def shared_versions(db: Session, version_ids: Sequence[uuid.UUID]) -> Sequence[tuple[Version, Question]]:
    """공유 시점 버전과 문항. 공유 뒤 삭제된 문항은 제외한다."""
    if not version_ids:
        return []
    return db.execute(
        select(Version, Question)
        .join(Question, Question.id == Version.question_id)
        .where(Version.id.in_(list(version_ids)), Question.deleted_at.is_(None))
        .order_by(Question.position, Question.id)
    ).all()
