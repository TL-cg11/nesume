"""자소서·버전 비즈니스 로직 (spec 3.1).

A6(리라이팅)은 후보 선택 시 `create_version(..., source="ai")`를 호출해 새 버전을 저장한다.
"""
import difflib
import re
import uuid
from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.features.resumes import pii_hooks
from app.features.resumes import repository as repo
from app.models import Question, Resume, User, Version
from app.retrieval import indexing

# spec 3.1 "버전은 문항당 최대 50개". 초과 시 압축 방식은 팀 확인 후 구현(part2_guide 4.14).
MAX_VERSIONS_PER_QUESTION = 50  # 문항당 버전 상한. 넘으면 저장 거부(10/26 회의, part2_guide 4.14·4.56)
MAX_RESUMES_PER_USER = 50       # 사용자당 자소서 상한(삭제되지 않은 것만 셈)


class ResumeLimitReached(ValueError):
    pass


class VersionLimitReached(ValueError):
    pass


class VersionInUse(ValueError):
    def __init__(self, by: str):
        self.by = by  # application / share
        super().__init__(by)
VERSION_SOURCES = ("manual", "ai")


def ensure_user(db: Session, user_id: str) -> None:
    """토큰의 sub로 users 행을 보장한다(소유 FK 대상). 이미 있으면 무시."""
    db.execute(insert(User).values(id=user_id).on_conflict_do_nothing(index_elements=[User.id]))


def create_resume(db: Session, owner_id: str, **fields) -> Resume:
    """자소서는 사용자당 50개까지. 넘으면 ResumeLimitReached(기존 자소서를 지워야 새로 만들 수 있음)."""
    ensure_user(db, owner_id)
    if repo.count_resumes(db, owner_id) >= MAX_RESUMES_PER_USER:
        raise ResumeLimitReached()
    resume = Resume(owner_id=owner_id, **fields)
    db.add(resume)
    db.flush()
    return resume


def update_resume(db: Session, resume: Resume, **fields) -> Resume:
    for k, v in fields.items():
        setattr(resume, k, v)
    db.flush()
    db.refresh(resume)
    return resume


def soft_delete_resume(db: Session, resume: Resume) -> None:
    # 물리 삭제·임베딩 삭제는 30일 후 B20(part2_guide 4.3). 검색 제외는 같은 트랜잭션에서 C3에 반영(4.39)
    resume.deleted_at = datetime.now(UTC)
    db.flush()
    indexing.mark_personal_deleted(db, source_id=resume.id, deleted_at=resume.deleted_at)


def create_question(db: Session, resume: Resume, title: str, char_limit: int | None,
                    position: int | None) -> Question:
    if position is None:
        position = len(repo.list_questions(db, resume.owner_id, resume.id))
    q = Question(resume_id=resume.id, owner_id=resume.owner_id, title=title,
                 char_limit=char_limit, position=position)
    db.add(q)
    db.flush()
    return q


def update_question(db: Session, question: Question, **fields) -> Question:
    for k, v in fields.items():
        setattr(question, k, v)
    db.flush()
    return question


def soft_delete_question(db: Session, question: Question) -> None:
    question.deleted_at = datetime.now(UTC)
    db.flush()


def create_version(
    db: Session,
    owner_id: str,
    resume_id: uuid.UUID,
    question_id: uuid.UUID,
    body: str,
    source: str,
    restored_from: uuid.UUID | None = None,
) -> tuple[Version, bool] | None:
    """새 버전을 저장한다(덮어쓰기 없음). 문항이 없거나 타인 소유면 None.

    본문에 민감정보가 있으면 pii_hooks.SensitiveInputBlocked. 문항에 버전이 이미 50개면 VersionLimitReached
    (사용자가 지울 버전을 골라 삭제한 뒤 저장, 4.56).
    반환: (버전, False) — 두 번째 값은 예전 '50개 초과' 표시로, 이제 초과 저장이 없어 항상 False(호환용)
    """
    if source not in VERSION_SOURCES:
        raise ValueError(f"unknown source: {source}")
    question = repo.get_question(db, owner_id, resume_id, question_id, for_update=True)
    if question is None:
        return None
    if repo.count_versions(db, question.id) >= MAX_VERSIONS_PER_QUESTION:
        raise VersionLimitReached()

    # 민감정보 거부 → 토큰화 → 대응표 저장(같은 트랜잭션, part2_guide 4.33)
    protected, vault_id = pii_hooks.protect_fields(db, owner_id, {"body": body})
    version = Version(
        question_id=question.id,
        owner_id=owner_id,
        version_no=repo.max_version_no(db, question.id) + 1,
        # 글자 수는 사용자가 입력한 원문 기준(공백 포함)
        char_count=len(body),
        body=protected["body"],
        vault_id=vault_id,
        source=source,
        restored_from=restored_from,
    )
    db.add(version)
    db.flush()
    db.refresh(version)
    return version, False


def restore_version(
    db: Session, owner_id: str, resume_id: uuid.UUID, question_id: uuid.UUID, version_id: uuid.UUID
) -> tuple[Version, bool] | None:
    """이전 버전 내용으로 새 버전을 만든다(manual, restored_from=원본)."""
    if repo.get_question(db, owner_id, resume_id, question_id) is None:
        return None
    source_version = repo.get_version(db, owner_id, question_id, version_id)
    if source_version is None:
        return None
    body = restore_body(db, owner_id, owner_id, source_version)
    return create_version(db, owner_id, resume_id, question_id, body, "manual",
                          restored_from=source_version.id)


def delete_version(db: Session, owner_id: str, version: Version) -> None:
    """버전 삭제(상한 50개를 넘기지 않게 사용자가 고른 것). 수정은 여전히 금지, 삭제만 허용.

    지원 기록이 고정 참조하는 버전(4.2), 유효한 멘토 공유가 고정한 버전(B10)은 지울 수 없다 → VersionInUse.
    """
    if repo.version_used_by_application(db, owner_id, version.id):
        raise VersionInUse("application")
    if repo.version_used_by_active_share(db, owner_id, version.id):
        raise VersionInUse("share")
    vault = version.vault_id
    db.delete(version)
    db.flush()
    pii_hooks.discard_vault(db, vault)


def restore_body(db: Session, owner_id: str, requester_id: str, version: Version) -> str:
    """버전 본문을 소유자 본인에게 원문으로 복원한다."""
    return pii_hooks.restore_fields(db, owner_id, requester_id, {"body": version.body}, version.vault_id)["body"]


_TOKEN = re.compile(r"\s+|[^\s]+")


def diff_segments(before: str, after: str) -> list[dict]:
    """단어(공백 보존) 단위 차이. 한국어 문단에서 줄 단위보다 읽기 쉽다."""
    a, b = _TOKEN.findall(before), _TOKEN.findall(after)
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        out.append({"op": op, "before": "".join(a[i1:i2]), "after": "".join(b[j1:j2])})
    return out


def dashboard(db: Session, owner_id: str, *, recent_limit: int = 4) -> dict:
    """홈 대시보드 집계(B, part2_guide 4.54). 상태 없음은 작성 중으로 센다."""
    resumes, questions, experience_total = repo.dashboard_counts(db, owner_id)
    latest = repo.latest_versions(db, [q.id for q in questions])
    by_resume: dict[uuid.UUID, list] = {}
    for q in questions:
        by_resume.setdefault(q.resume_id, []).append(q)
    titles = {r.id: r.title for r in resumes}

    def last_edited(r):
        times = [r.updated_at] + [latest[q.id].created_at for q in by_resume.get(r.id, []) if q.id in latest]
        return max(times)

    newest = max(latest.values(), key=lambda v: v.created_at, default=None)
    qmap = {q.id: q for q in questions}
    filled = len(latest)
    return {
        "resume_total": len(resumes),
        "resume_in_progress": sum(r.status != "완료" for r in resumes),
        "experience_total": experience_total or 0,
        "question_total": len(questions),
        "question_filled": filled,
        "progress_percent": round(filled * 100 / len(questions)) if questions else 0,
        "latest_save": None if newest is None else {
            "resume_id": qmap[newest.question_id].resume_id,
            "resume_title": titles[qmap[newest.question_id].resume_id],
            "question_title": qmap[newest.question_id].title,
            "version_no": newest.version_no, "created_at": newest.created_at,
        },
        "recent": [
            {"id": r.id, "title": r.title, "status": r.status, "question_count": len(by_resume.get(r.id, [])),
             "last_edited_at": last_edited(r)}
            for r in sorted(resumes, key=last_edited, reverse=True)[:recent_limit]
        ],
    }
