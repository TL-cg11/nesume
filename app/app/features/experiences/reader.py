"""다른 팀용 경험 읽기 함수 (A11 요청, part2_guide 4.34).

B 내부 repository·service를 직접 조합하지 않고 이 모듈만 쓴다.
- 소유자 본인 데이터만, 소프트 삭제 제외(repository)
- 값은 원문으로 복원해서 준다. DB 값은 문서 단위 토큰이라 여러 건을 합치면 번호가 겹친다.
  LLM에 보낼 때는 A8을 거쳐 A1이 한 번에 다시 토큰화한다.
"""
from sqlalchemy.orm import Session

from app.features.experiences import repository as repo
from app.features.experiences import service

MAX_LIMIT = 100  # B5 목록 API와 같은 상한


def list_owner_experiences(db: Session, owner_id: str, *, limit: int = 50, offset: int = 0) -> list[dict]:
    """owner_id의 경험 목록(원문). 정렬은 B5 목록과 같다(기간 시작 최신순)."""
    if not 1 <= limit <= MAX_LIMIT or offset < 0:
        raise ValueError("limit은 1~100, offset은 0 이상")
    rows = repo.list_experiences(db, owner_id, [], limit, offset)
    return [service.to_owner_view(db, owner_id, owner_id, e) for e in rows]
