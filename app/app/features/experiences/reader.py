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


def tokenized_experience_docs(db: Session) -> list[dict]:
    """C3 색인 배치 전용 — 삭제 안 된 모든 경험의 **토큰화 상태 값**(원문 복원 안 함)을 글 1개로.

    API 응답·로그로 내보내지 않는다(서버 안 배치 전용). 경험은 공유가 없어 `shared_with`는 빈 값.
    """
    from sqlalchemy import select

    from app.models.experience import Experience

    rows = db.scalars(select(Experience).where(Experience.deleted_at.is_(None))).all()
    out = []
    for e in rows:
        lists = (" ".join(e.tech_stack or []), " ".join(e.tags or []))
        parts = [e.title, e.type, e.role, e.outcome, e.detail, *lists]
        out.append({
            "id": e.id,
            "owner_id": e.owner_id,
            "grade": e.grade,
            "shared_with": [],
            "text": "\n".join(p for p in parts if p),
        })
    return out
