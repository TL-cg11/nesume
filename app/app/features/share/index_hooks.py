"""공유 변경을 벡터 메타데이터에 반영하는 지점 (tasks B10, part2_guide 4.39).

반드시 공유 변경과 같은 트랜잭션(같은 세션)에서 호출한다. 실제 갱신은 C3 `sync_shared_with`.
"""
import uuid

from sqlalchemy.orm import Session

from app.retrieval import indexing


def sync_shared_with(db: Session, resume_id: uuid.UUID, shared_with: list[dict]) -> None:
    indexing.sync_shared_with(db, source_id=resume_id, shared_with=shared_with)
