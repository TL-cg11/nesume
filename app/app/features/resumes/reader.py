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


def tokenized_resume_docs(db: Session) -> list[dict]:
    """C3 색인 배치 전용 — 삭제 안 된 모든 자소서의 **토큰화 상태 본문**(원문 복원 안 함).

    문항 순서대로 최신 버전 본문을 이어 붙인다. 등급·공유 메타(`grade`·`shared_with`)를 같이 준다 —
    C3가 벡터 행에 복제해 C6 사전 필터가 쓴다. API 응답·로그로 내보내지 않는다(서버 안 배치 전용).
    """
    from sqlalchemy import select

    from app.models.resume import Question, Resume

    resumes = db.scalars(select(Resume).where(Resume.deleted_at.is_(None))).all()
    if not resumes:
        return []
    questions = db.scalars(
        select(Question)
        .where(Question.resume_id.in_([r.id for r in resumes]), Question.deleted_at.is_(None))
        .order_by(Question.resume_id, Question.position, Question.id)
    ).all()
    latest = repo.latest_versions(db, [q.id for q in questions])
    bodies: dict = {}
    for q in questions:
        v = latest.get(q.id)
        if v is not None and v.body:
            bodies.setdefault(q.resume_id, []).append(v.body)
    return [
        {
            "id": r.id,
            "owner_id": r.owner_id,
            "grade": r.grade,
            "shared_with": list(r.shared_with or []),
            "text": "\n\n".join(bodies.get(r.id, [])),
        }
        for r in resumes
    ]
