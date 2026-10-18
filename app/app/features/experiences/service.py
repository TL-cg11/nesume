"""경험 데이터 비즈니스 로직 (spec 3.5).

저장 경로: 민감정보 차단(A1) → 문자열 필드 토큰화(A1, B7) → 저장 → 개인 인덱스 반영(C3).
조회 경로: 소유자 본인에게만 토큰 복원.
"""
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.features.experiences import index_hooks
from app.features.experiences import repository as repo
from app.features.resumes import pii_hooks
from app.features.resumes.service import ensure_user
from app.models import Experience, QuestionExperience

# PII가 들어갈 수 있는 문자열 필드 전부(part2_guide 4.20)
TEXT_FIELDS = ("title", "type", "role", "outcome", "detail")
LIST_FIELDS = ("tech_stack", "tags")


def _check_and_tokenize(owner_id: str, fields: dict) -> dict:
    out = dict(fields)
    for name in TEXT_FIELDS:
        if out.get(name) is not None:
            pii_hooks.ensure_no_sensitive(out[name])
            out[name] = pii_hooks.tokenize_for_storage(owner_id, out[name])
    for name in LIST_FIELDS:
        if out.get(name) is not None:
            for item in out[name]:
                pii_hooks.ensure_no_sensitive(item)
            out[name] = [pii_hooks.tokenize_for_storage(owner_id, item) for item in out[name]]
    return out


def to_owner_view(owner_id: str, requester_id: str, e: Experience) -> dict:
    """응답용. 토큰은 소유자 본인에게만 원문으로 복원한다."""
    def restore(v):
        return None if v is None else pii_hooks.restore_for_owner(owner_id, requester_id, v)

    return {
        "id": e.id,
        "title": restore(e.title),
        "type": restore(e.type),
        "period_start": e.period_start,
        "period_end": e.period_end,
        "role": restore(e.role),
        "tech_stack": [restore(t) for t in e.tech_stack],
        "outcome": restore(e.outcome),
        "detail": restore(e.detail),
        "tags": [restore(t) for t in e.tags],
        "created_at": e.created_at,
        "updated_at": e.updated_at,
    }


def tokenize_tag_filter(owner_id: str, tags: list[str]) -> list[str]:
    """저장값이 토큰화 상태이므로 필터 값도 같은 처리를 거친다."""
    return [pii_hooks.tokenize_for_storage(owner_id, t) for t in tags]


def create_experience(db: Session, owner_id: str, fields: dict) -> Experience:
    ensure_user(db, owner_id)
    e = Experience(owner_id=owner_id, **_check_and_tokenize(owner_id, fields))
    db.add(e)
    db.flush()
    db.refresh(e)
    index_hooks.index_experience(owner_id, e.id)
    return e


def update_experience(db: Session, owner_id: str, e: Experience, fields: dict) -> Experience:
    for k, v in _check_and_tokenize(owner_id, fields).items():
        setattr(e, k, v)
    db.flush()
    db.refresh(e)
    index_hooks.index_experience(owner_id, e.id)
    return e


def soft_delete_experience(db: Session, e: Experience) -> None:
    # 물리 삭제·임베딩 삭제는 30일 후 B20(part2_guide 4.19)
    e.deleted_at = datetime.now(UTC)
    db.flush()


def link(db: Session, owner_id: str, question_id: uuid.UUID, experience_id: uuid.UUID) -> bool:
    """문항에 경험을 연결한다. 이미 연결돼 있으면 False."""
    if repo.get_link(db, owner_id, question_id, experience_id) is not None:
        return False
    db.add(QuestionExperience(question_id=question_id, experience_id=experience_id, owner_id=owner_id))
    db.flush()
    return True
