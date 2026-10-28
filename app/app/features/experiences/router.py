"""경험 데이터 API (B5, spec 3.5). 소유자 본인만 접근, 타인 리소스는 404."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.auth import AuthenticatedUser
from app.db import get_db
from app.features.experiences import repository as repo
from app.features.experiences import service
from app.features.experiences.schemas import ExperienceCreate, ExperienceOut, ExperienceUpdate, LinkCreate
from app.features.resumes import pii_hooks
from app.features.resumes import repository as resume_repo

router = APIRouter(prefix="/experiences", tags=["experiences"])
links_router = APIRouter(prefix="/resumes/{resume_id}/questions/{question_id}/experiences", tags=["experiences"])
Db = Annotated[Session, Depends(get_db)]

_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
# 안내 문구는 spec 9.1 block(민감정보)
_SENSITIVE = HTTPException(
    status.HTTP_422_UNPROCESSABLE_CONTENT,
    "주민번호·계좌번호 등 민감정보는 제공하지 않습니다. 입력 시에도 자동 차단됩니다.",
)


def _experience_or_404(db: Session, owner_id: str, experience_id: uuid.UUID):
    e = repo.get_experience(db, owner_id, experience_id)
    if e is None:
        raise _NOT_FOUND
    return e


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ExperienceOut)
def create_experience(payload: ExperienceCreate, user: AuthenticatedUser, db: Db):
    try:
        e = service.create_experience(db, user.sub, payload.model_dump())
    except pii_hooks.SensitiveInputBlocked:
        raise _SENSITIVE from None
    return service.to_owner_view(db, user.sub, user.sub, e)


@router.get("", response_model=list[ExperienceOut])
def list_experiences(
    user: AuthenticatedUser,
    db: Db,
    tags: Annotated[list[str], Query()] = [],  # noqa: B006 (FastAPI 쿼리 기본값)
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    rows = repo.list_experiences(db, user.sub, service.tag_filter_values(tags), limit, offset)
    return [service.to_owner_view(db, user.sub, user.sub, e) for e in rows]


@router.get("/{experience_id}", response_model=ExperienceOut)
def get_experience(experience_id: uuid.UUID, user: AuthenticatedUser, db: Db):
    return service.to_owner_view(db, user.sub, user.sub, _experience_or_404(db, user.sub, experience_id))


@router.patch("/{experience_id}", response_model=ExperienceOut)
def update_experience(experience_id: uuid.UUID, payload: ExperienceUpdate, user: AuthenticatedUser, db: Db):
    e = _experience_or_404(db, user.sub, experience_id)
    try:
        e = service.update_experience(db, user.sub, e, payload.model_dump(exclude_unset=True))
    except pii_hooks.SensitiveInputBlocked:
        raise _SENSITIVE from None
    return service.to_owner_view(db, user.sub, user.sub, e)


@router.delete("/{experience_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_experience(experience_id: uuid.UUID, user: AuthenticatedUser, db: Db):
    service.soft_delete_experience(db, _experience_or_404(db, user.sub, experience_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- 자소서 문항에 끌어오기(연결 기록) --------------------------------------

def _question_or_404(db: Session, owner_id: str, resume_id: uuid.UUID, question_id: uuid.UUID):
    q = resume_repo.get_question(db, owner_id, resume_id, question_id)
    if q is None:
        raise _NOT_FOUND
    return q


@links_router.get("", response_model=list[ExperienceOut])
def list_linked(resume_id: uuid.UUID, question_id: uuid.UUID, user: AuthenticatedUser, db: Db):
    _question_or_404(db, user.sub, resume_id, question_id)
    return [service.to_owner_view(db, user.sub, user.sub, e)
            for e in repo.linked_experiences(db, user.sub, question_id)]


@links_router.post("", response_model=ExperienceOut)
def link_experience(
    resume_id: uuid.UUID, question_id: uuid.UUID, payload: LinkCreate, user: AuthenticatedUser,
    db: Db, response: Response,
):
    _question_or_404(db, user.sub, resume_id, question_id)
    e = _experience_or_404(db, user.sub, payload.experience_id)
    created = service.link(db, user.sub, question_id, e.id)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return service.to_owner_view(db, user.sub, user.sub, e)


@links_router.delete("/{experience_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_experience(
    resume_id: uuid.UUID, question_id: uuid.UUID, experience_id: uuid.UUID, user: AuthenticatedUser, db: Db
):
    _question_or_404(db, user.sub, resume_id, question_id)
    link = repo.get_link(db, user.sub, question_id, experience_id)
    if link is None:
        raise _NOT_FOUND
    db.delete(link)
    db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# B14 GitHub 프로젝트 소개(/experiences/github/draft). 결과는 경험 데이터로 저장하므로 경험 API 아래에 둔다.
# main.py(D) 등록 없이 동작하도록 이 라우터에 붙인다(part2_guide 4.60).
from app.features.github.router import router as _github_router  # noqa: E402

router.include_router(_github_router)
