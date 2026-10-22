"""자소서 CRUD + 버전 관리 API (B4, spec 3.1).

모든 엔드포인트는 소유자 본인만 접근한다. 타인 리소스는 404(존재 여부 비노출).
멘토 열람(B10), 운영자 mask 열람(spec 6.3)은 해당 태스크에서 추가한다.
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.auth import AuthenticatedUser
from app.db import get_db
from app.features.resumes import pii_hooks
from app.features.resumes import repository as repo
from app.features.resumes import service
from app.features.resumes.schemas import (
    QuestionCreate,
    QuestionOut,
    QuestionUpdate,
    ResumeCreate,
    ResumeDetail,
    ResumeOut,
    ResumeUpdate,
    VersionCreate,
    VersionCreated,
    VersionDiff,
    VersionOut,
    VersionSummary,
)

router = APIRouter(prefix="/resumes", tags=["resumes"])
Db = Annotated[Session, Depends(get_db)]

_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


def _resume_or_404(db: Session, owner_id: str, resume_id: uuid.UUID):
    resume = repo.get_resume(db, owner_id, resume_id)
    if resume is None:
        raise _NOT_FOUND
    return resume


def _question_or_404(db: Session, owner_id: str, resume_id: uuid.UUID, question_id: uuid.UUID):
    question = repo.get_question(db, owner_id, resume_id, question_id)
    if question is None:
        raise _NOT_FOUND
    return question


def _version_out(db: Session, owner_id: str, requester_id: str, v) -> dict:
    data = VersionSummary.model_validate(v).model_dump()
    data["body"] = service.restore_body(db, owner_id, requester_id, v)
    return data


# 안내 문구는 spec 9.1 block(민감정보)
_SENSITIVE = HTTPException(
    status.HTTP_422_UNPROCESSABLE_CONTENT,
    "주민번호·계좌번호 등 민감정보는 제공하지 않습니다. 입력 시에도 자동 차단됩니다.",
)


# --- 자소서 -----------------------------------------------------------------

@router.post("", status_code=status.HTTP_201_CREATED, response_model=ResumeOut)
def create_resume(payload: ResumeCreate, user: AuthenticatedUser, db: Db):
    return service.create_resume(db, user.sub, **payload.model_dump())


@router.get("", response_model=list[ResumeOut])
def list_resumes(
    user: AuthenticatedUser,
    db: Db,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return repo.list_resumes(db, user.sub, limit, offset)


@router.get("/{resume_id}", response_model=ResumeDetail)
def get_resume(resume_id: uuid.UUID, user: AuthenticatedUser, db: Db):
    resume = _resume_or_404(db, user.sub, resume_id)
    questions = repo.list_questions(db, user.sub, resume.id)
    latest = repo.latest_versions(db, [q.id for q in questions])
    return {
        **ResumeOut.model_validate(resume).model_dump(),
        "questions": [
            {**QuestionOut.model_validate(q).model_dump(exclude={"latest_version"}),
             "latest_version": latest.get(q.id)}
            for q in questions
        ],
    }


@router.patch("/{resume_id}", response_model=ResumeOut)
def update_resume(resume_id: uuid.UUID, payload: ResumeUpdate, user: AuthenticatedUser, db: Db):
    resume = _resume_or_404(db, user.sub, resume_id)
    return service.update_resume(db, resume, **payload.model_dump(exclude_unset=True))


@router.delete("/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_resume(resume_id: uuid.UUID, user: AuthenticatedUser, db: Db):
    service.soft_delete_resume(db, _resume_or_404(db, user.sub, resume_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- 문항 -------------------------------------------------------------------

@router.post("/{resume_id}/questions", status_code=status.HTTP_201_CREATED, response_model=QuestionOut)
def create_question(resume_id: uuid.UUID, payload: QuestionCreate, user: AuthenticatedUser, db: Db):
    resume = _resume_or_404(db, user.sub, resume_id)
    return service.create_question(db, resume, **payload.model_dump())


@router.patch("/{resume_id}/questions/{question_id}", response_model=QuestionOut)
def update_question(
    resume_id: uuid.UUID, question_id: uuid.UUID, payload: QuestionUpdate, user: AuthenticatedUser, db: Db
):
    question = _question_or_404(db, user.sub, resume_id, question_id)
    return service.update_question(db, question, **payload.model_dump(exclude_unset=True))


@router.delete("/{resume_id}/questions/{question_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_question(resume_id: uuid.UUID, question_id: uuid.UUID, user: AuthenticatedUser, db: Db):
    service.soft_delete_question(db, _question_or_404(db, user.sub, resume_id, question_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- 버전 -------------------------------------------------------------------

@router.post(
    "/{resume_id}/questions/{question_id}/versions",
    status_code=status.HTTP_201_CREATED,
    response_model=VersionCreated,
)
def create_version(
    resume_id: uuid.UUID, question_id: uuid.UUID, payload: VersionCreate, user: AuthenticatedUser, db: Db
):
    try:
        result = service.create_version(db, user.sub, resume_id, question_id, payload.body, "manual")
    except pii_hooks.SensitiveInputBlocked:
        raise _SENSITIVE from None
    if result is None:
        raise _NOT_FOUND
    version, over_limit = result
    return {**_version_out(db, user.sub, user.sub, version), "over_limit": over_limit}


@router.get("/{resume_id}/questions/{question_id}/versions", response_model=list[VersionSummary])
def list_versions(resume_id: uuid.UUID, question_id: uuid.UUID, user: AuthenticatedUser, db: Db):
    _question_or_404(db, user.sub, resume_id, question_id)
    return repo.list_versions(db, user.sub, question_id)


@router.get("/{resume_id}/questions/{question_id}/versions/diff", response_model=VersionDiff)
def diff_versions(
    resume_id: uuid.UUID,
    question_id: uuid.UUID,
    user: AuthenticatedUser,
    db: Db,
    from_no: Annotated[int, Query(alias="from", ge=1)],
    to_no: Annotated[int, Query(alias="to", ge=1)],
):
    _question_or_404(db, user.sub, resume_id, question_id)
    a = repo.get_version_by_no(db, user.sub, question_id, from_no)
    b = repo.get_version_by_no(db, user.sub, question_id, to_no)
    if a is None or b is None:
        raise _NOT_FOUND
    before = service.restore_body(db, user.sub, user.sub, a)
    after = service.restore_body(db, user.sub, user.sub, b)
    return {"from_version": from_no, "to_version": to_no,
            "segments": service.diff_segments(before, after)}


@router.get("/{resume_id}/questions/{question_id}/versions/{version_id}", response_model=VersionOut)
def get_version(
    resume_id: uuid.UUID, question_id: uuid.UUID, version_id: uuid.UUID, user: AuthenticatedUser, db: Db
):
    _question_or_404(db, user.sub, resume_id, question_id)
    version = repo.get_version(db, user.sub, question_id, version_id)
    if version is None:
        raise _NOT_FOUND
    return _version_out(db, user.sub, user.sub, version)


@router.post(
    "/{resume_id}/questions/{question_id}/versions/{version_id}/restore",
    status_code=status.HTTP_201_CREATED,
    response_model=VersionCreated,
)
def restore_version(
    resume_id: uuid.UUID, question_id: uuid.UUID, version_id: uuid.UUID, user: AuthenticatedUser, db: Db
):
    result = service.restore_version(db, user.sub, resume_id, question_id, version_id)
    if result is None:
        raise _NOT_FOUND
    version, over_limit = result
    return {**_version_out(db, user.sub, user.sub, version), "over_limit": over_limit}
