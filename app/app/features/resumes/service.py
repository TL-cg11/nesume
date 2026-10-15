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

# spec 3.1 "버전은 문항당 최대 50개". 초과 시 압축 방식은 팀 확인 후 구현(part2_guide 4.14).
MAX_VERSIONS_PER_QUESTION = 50
VERSION_SOURCES = ("manual", "ai")


def ensure_user(db: Session, user_id: str) -> None:
    """토큰의 sub로 users 행을 보장한다(소유 FK 대상). 이미 있으면 무시."""
    db.execute(insert(User).values(id=user_id).on_conflict_do_nothing(index_elements=[User.id]))


def create_resume(db: Session, owner_id: str, **fields) -> Resume:
    ensure_user(db, owner_id)
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
    # 물리 삭제·임베딩 삭제는 30일 후 B20(part2_guide 4.3)
    resume.deleted_at = datetime.now(UTC)
    db.flush()


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

    반환: (버전, 문항당 50개 초과 여부)
    """
    if source not in VERSION_SOURCES:
        raise ValueError(f"unknown source: {source}")
    question = repo.get_question(db, owner_id, resume_id, question_id, for_update=True)
    if question is None:
        return None

    version = Version(
        question_id=question.id,
        owner_id=owner_id,
        version_no=repo.max_version_no(db, question.id) + 1,
        # 글자 수는 사용자가 입력한 원문 기준(공백 포함)
        char_count=len(body),
        body=pii_hooks.tokenize_for_storage(owner_id, body),
        source=source,
        restored_from=restored_from,
    )
    db.add(version)
    db.flush()
    db.refresh(version)
    over_limit = repo.count_versions(db, question.id) > MAX_VERSIONS_PER_QUESTION
    return version, over_limit


def restore_version(
    db: Session, owner_id: str, resume_id: uuid.UUID, question_id: uuid.UUID, version_id: uuid.UUID
) -> tuple[Version, bool] | None:
    """이전 버전 내용으로 새 버전을 만든다(manual, restored_from=원본)."""
    if repo.get_question(db, owner_id, resume_id, question_id) is None:
        return None
    source_version = repo.get_version(db, owner_id, question_id, version_id)
    if source_version is None:
        return None
    body = pii_hooks.restore_for_owner(owner_id, owner_id, source_version.body)
    return create_version(db, owner_id, resume_id, question_id, body, "manual",
                          restored_from=source_version.id)


_TOKEN = re.compile(r"\s+|[^\s]+")


def diff_segments(before: str, after: str) -> list[dict]:
    """단어(공백 보존) 단위 차이. 한국어 문단에서 줄 단위보다 읽기 쉽다."""
    a, b = _TOKEN.findall(before), _TOKEN.findall(after)
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        out.append({"op": op, "before": "".join(a[i1:i2]), "after": "".join(b[j1:j2])})
    return out
