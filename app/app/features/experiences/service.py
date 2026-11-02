"""경험 데이터 비즈니스 로직 (spec 3.5).

저장 경로: 민감정보 차단(A1) → 문자열 필드 토큰화(A1) + 대응표 저장(B7) → 저장 → 개인 인덱스 반영(C3).
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
from app.retrieval import indexing

# PII가 들어갈 수 있는 문자열 필드 전부(part2_guide 4.20)
TEXT_FIELDS = ("title", "type", "role", "outcome", "detail")
LIST_FIELDS = ("tech_stack", "tags")


_PII_FIELDS = TEXT_FIELDS + LIST_FIELDS


def _raw_fields(db: Session, owner_id: str, e: Experience) -> dict:
    """저장된 PII 대상 필드를 원문으로 복원한다(소유자 본인 경로 전용)."""
    stored = {name: getattr(e, name) for name in _PII_FIELDS}
    return pii_hooks.restore_fields(db, owner_id, owner_id, stored, e.vault_id)


def _protect(db: Session, owner_id: str, fields: dict) -> dict:
    """민감정보 거부 → 토큰화 → 대응표 저장. vault_id를 포함한 저장용 필드를 돌려준다."""
    pii = {k: v for k, v in fields.items() if k in _PII_FIELDS}
    protected, vault_id = pii_hooks.protect_fields(db, owner_id, pii)
    return {**fields, **protected, "vault_id": vault_id}


def to_owner_view(db: Session, owner_id: str, requester_id: str, e: Experience) -> dict:
    """응답용. 토큰은 소유자 본인에게만 원문으로 복원한다."""
    stored = {name: getattr(e, name) for name in _PII_FIELDS}
    raw = pii_hooks.restore_fields(db, owner_id, requester_id, stored, e.vault_id)
    return {
        "id": e.id,
        "title": raw["title"],
        "type": raw["type"],
        "period_start": e.period_start,
        "period_end": e.period_end,
        "role": raw["role"],
        "tech_stack": raw["tech_stack"],
        "outcome": raw["outcome"],
        "detail": raw["detail"],
        "tags": raw["tags"],
        "created_at": e.created_at,
        "updated_at": e.updated_at,
    }


def tag_filter_values(tags: list[str]) -> list[str]:
    """태그 필터는 입력값 그대로 비교한다. 개인정보가 든 태그는 토큰으로 저장돼 검색되지 않는다(part2_guide 4.33)."""
    return list(tags)


def create_experience(db: Session, owner_id: str, fields: dict) -> Experience:
    ensure_user(db, owner_id)
    e = Experience(owner_id=owner_id, **_protect(db, owner_id, fields))
    db.add(e)
    db.flush()
    db.refresh(e)
    index_hooks.index_experience(db, owner_id, e.id)
    return e


def update_experience(db: Session, owner_id: str, e: Experience, fields: dict) -> Experience:
    # 토큰 번호는 문서(대응표) 단위라, 일부 필드만 바뀌어도 전체를 원문으로 되돌린 뒤 새 대응표로 다시 토큰화한다.
    old_vault = e.vault_id
    merged = {**_raw_fields(db, owner_id, e), **fields}
    for k, v in _protect(db, owner_id, merged).items():
        setattr(e, k, v)
    db.flush()
    pii_hooks.discard_vault(db, old_vault)
    db.refresh(e)
    index_hooks.index_experience(db, owner_id, e.id)
    return e


def soft_delete_experience(db: Session, e: Experience) -> None:
    # 물리 삭제·임베딩 삭제는 30일 후 B20(part2_guide 4.19). 검색 제외는 같은 트랜잭션에서 C3에 반영(4.39)
    e.deleted_at = datetime.now(UTC)
    db.flush()
    indexing.mark_personal_deleted(db, source_id=e.id, deleted_at=e.deleted_at)


def link(db: Session, owner_id: str, question_id: uuid.UUID, experience_id: uuid.UUID) -> bool:
    """문항에 경험을 연결한다. 이미 연결돼 있으면 False."""
    if repo.get_link(db, owner_id, question_id, experience_id) is not None:
        return False
    db.add(QuestionExperience(question_id=question_id, experience_id=experience_id, owner_id=owner_id))
    db.flush()
    return True
