"""다른 팀용 자소서 읽기 함수 (A11 요청, part2_guide 4.34).

B 내부 repository·service를 직접 조합하지 않고 이 모듈만 쓴다.
- 소유자 본인 데이터만, 소프트 삭제 제외(repository)
- 본문은 원문으로 복원해서 준다. LLM에 보낼 때는 A8을 거친다.
"""
import uuid

from sqlalchemy.orm import Session

from app.features.resumes import repository as repo
from app.features.resumes import service


def resume_bodies(db: Session, owner_id: str, resume_id: uuid.UUID) -> list[dict] | None:
    """문항별 최신 버전 본문(원문). 자소서가 없거나 타인 소유면 None.

    버전이 없는 문항은 body·version_id가 None.
    """
    if repo.get_resume(db, owner_id, resume_id) is None:
        return None
    questions = repo.list_questions(db, owner_id, resume_id)
    latest = repo.latest_versions(db, [q.id for q in questions])
    out = []
    for q in questions:
        v = latest.get(q.id)
        out.append({
            "question_id": q.id,
            "title": q.title,
            "char_limit": q.char_limit,
            "version_id": v.id if v else None,
            "body": service.restore_body(db, owner_id, owner_id, v) if v else None,
        })
    return out
