"""공유 변경을 벡터 메타데이터에 반영하는 지점 (tasks B10, part2_guide 4.39).

C `retrieval.indexing.sync_shared_with`가 main에 병합되면(현재 C 브랜치) 이 함수 본문만 교체한다.
반드시 공유 변경과 같은 트랜잭션(같은 세션)에서 호출한다.
"""
import uuid

from sqlalchemy.orm import Session


def sync_shared_with(db: Session, resume_id: uuid.UUID, shared_with: list[dict]) -> None:
    return None
