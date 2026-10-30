"""자소서 CRUD + 버전 관리 API (B4, spec 3.1).

모든 엔드포인트는 소유자 본인만 접근한다. 타인 리소스는 404(존재 여부 비노출).
멘토 열람(B10), 운영자 mask 열람(spec 6.3)은 해당 태스크에서 추가한다.
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.auth import AuthenticatedUser
from app.core.errors import AppError
from app.db import get_db
from app.features.resumes import pii_hooks
from app.features.resumes import repository as repo
from app.features.resumes import service
from app.features.resumes.schemas import (
    Dashboard,
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
from app.features.share import service as share_service

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


def _limit_resumes() -> AppError:
    return AppError(
        f"자기소개서는 {service.MAX_RESUMES_PER_USER}개까지 만들 수 있습니다. 기존 자기소개서를 삭제한 뒤 새로 만들어 주세요.",
        code="resume_limit_reached", status_code=409,
    )


def _limit_versions() -> AppError:
    return AppError(
        f"문항당 버전은 {service.MAX_VERSIONS_PER_QUESTION}개까지 저장됩니다. 지울 버전을 골라 삭제한 뒤 저장해 주세요.",
        code="version_limit_reached", status_code=409,
    )
_IN_USE = {
    "application": "지원 기록에 쓰인 버전은 삭제할 수 없습니다.",
    "share": "멘토에게 공유 중인 버전은 삭제할 수 없습니다. 공유가 끝난 뒤 삭제해 주세요.",
}


# 안내 문구는 spec 9.1 block(민감정보)
_SENSITIVE = HTTPException(
    status.HTTP_422_UNPROCESSABLE_CONTENT,
    "주민번호·계좌번호 등 민감정보는 제공하지 않습니다. 입력 시에도 자동 차단됩니다.",
)


# --- 자소서 -----------------------------------------------------------------

@router.post("", status_code=status.HTTP_201_CREATED, response_model=ResumeOut)
def create_resume(payload: ResumeCreate, user: AuthenticatedUser, db: Db):
    try:
        return service.create_resume(db, user.sub, **payload.model_dump())
    except service.ResumeLimitReached:
        raise _limit_resumes() from None


@router.get("", response_model=list[ResumeOut])
def list_resumes(
    user: AuthenticatedUser,
    db: Db,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    rows = repo.list_resumes(db, user.sub, limit, offset)
    summaries = share_service.resume_summaries(db, user.sub, [r.id for r in rows])
    return [{**ResumeOut.model_validate(r).model_dump(), "share_summary": summaries.get(r.id)} for r in rows]


@router.get("/dashboard", response_model=Dashboard)
def get_dashboard(user: AuthenticatedUser, db: Db):
    """홈 대시보드(사용자용). `/{resume_id}`보다 먼저 둔다(경로 충돌 방지)."""
    data = service.dashboard(db, user.sub)
    summaries = share_service.resume_summaries(db, user.sub, [r["id"] for r in data["recent"]])
    for r in data["recent"]:
        r["share_summary"] = summaries.get(r["id"])
    return data


@router.get("/{resume_id}", response_model=ResumeDetail)
def get_resume(resume_id: uuid.UUID, user: AuthenticatedUser, db: Db):
    resume = _resume_or_404(db, user.sub, resume_id)
    questions = repo.list_questions(db, user.sub, resume.id)
    latest = repo.latest_versions(db, [q.id for q in questions])
    return {
        **ResumeOut.model_validate(resume).model_dump(),
        "share_summary": share_service.resume_summaries(db, user.sub, [resume.id]).get(resume.id),
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
    except service.VersionLimitReached:
        raise _limit_versions() from None
    if result is None:
        raise _NOT_FOUND
    version, over_limit = result
    return {**_version_out(db, user.sub, user.sub, version), "over_limit": over_limit}


@router.get("/{resume_id}/questions/{question_id}/versions", response_model=list[VersionSummary])
def list_versions(
    resume_id: uuid.UUID, question_id: uuid.UUID, user: AuthenticatedUser, db: Db, include_ended: bool = False,
):
    """버전 타임라인 + 버전별 멘토 공유 태그. include_ended=true면 만료·취소된 공유도 포함(4.43)."""
    _question_or_404(db, user.sub, resume_id, question_id)
    rows = repo.list_versions(db, user.sub, question_id)
    tags = share_service.version_tags(db, user.sub, [v.id for v in rows], include_ended=include_ended)
    return [{**VersionSummary.model_validate(v).model_dump(), "shares": tags[v.id]} for v in rows]


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


@router.delete("/{resume_id}/questions/{question_id}/versions/{version_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_version(
    resume_id: uuid.UUID, question_id: uuid.UUID, version_id: uuid.UUID, user: AuthenticatedUser, db: Db
):
    """버전 삭제(문항당 50개 상한, 4.56). 지원 기록·유효한 멘토 공유가 쓰는 버전은 409."""
    _question_or_404(db, user.sub, resume_id, question_id)
    version = repo.get_version(db, user.sub, question_id, version_id)
    if version is None:
        raise _NOT_FOUND
    try:
        service.delete_version(db, user.sub, version)
    except service.VersionInUse as e:
        raise AppError(_IN_USE[e.by], code="version_in_use", status_code=409, errors={"by": e.by}) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{resume_id}/questions/{question_id}/versions/{version_id}/restore",
    status_code=status.HTTP_201_CREATED,
    response_model=VersionCreated,
)
def restore_version(
    resume_id: uuid.UUID, question_id: uuid.UUID, version_id: uuid.UUID, user: AuthenticatedUser, db: Db
):
    try:
        result = service.restore_version(db, user.sub, resume_id, question_id, version_id)
    except service.VersionLimitReached:
        raise _limit_versions() from None
    if result is None:
        raise _NOT_FOUND
    version, over_limit = result
    return {**_version_out(db, user.sub, user.sub, version), "over_limit": over_limit}


# B12 PDF(/resumes/{id}/pdf). 자소서 라우터 아래에 붙여 main.py(D) 등록 없이 동작한다.
from app.features.pdf.router import router as _pdf_router  # noqa: E402

router.include_router(_pdf_router)
