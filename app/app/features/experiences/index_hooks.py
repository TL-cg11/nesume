"""개인 인덱스 반영 지점 (tasks B5 "저장 후 C3로 개인 인덱스 반영").

11/2 연결: 등록·수정 뒤 `personal_index.mark` → 커밋 뒤 백그라운드에서 임베딩(EMBEDDING_URL 있을 때).
소프트 삭제 반영은 service에서 C3 mark_personal_deleted 호출.
"""
import uuid

from sqlalchemy.orm import Session

from app.features import personal_index


def index_experience(db: Session, owner_id: str, experience_id: uuid.UUID) -> None:
    """등록·수정 후 호출. 커밋 뒤 토큰화된 경험 글을 개인 인덱스에 다시 넣는다."""
    personal_index.mark(db, "experience", experience_id)
