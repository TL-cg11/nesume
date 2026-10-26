"""멘토 공유 API (tasks B10, spec 3.7).

소유자: 공유 생성·목록·연장·취소. 멘토(토큰 role=mentor): 받은 공유 목록, 공유된 버전 읽기 전용 열람.
다른 사람의 자소서·공유, 끝난 공유는 404. 멘토 API는 멘토 역할이 아니면 403.
main.py(D 소유) 등록은 D에 요청한다.
"""
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.auth import AuthenticatedUser, CurrentUser, Role
from app.core.errors import ConflictError
from app.db import get_db
from app.features.resumes import pii_hooks
from app.features.resumes.service import ensure_user
from app.features.share import period, service
from app.features.share import repository as repo
from app.features.share.schemas import (
    ReceivedShare, SharedQuestion, SharedResume, ShareCreate, ShareExtend, ShareOut, ShareRename,
)
from app.models import Share

owner_router = APIRouter(tags=["shares"])
mentor_router = APIRouter(prefix="/mentor/shares", tags=["shares"])

Db = Annotated[Session, Depends(get_db)]
_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
_PERIOD = HTTPException(
    status.HTTP_422_UNPROCESSABLE_CONTENT, f"공유 기간은 오늘부터 {period.MAX_DAYS}일 이내로 선택해 주세요."
)


_SENSITIVE = HTTPException(
    status.HTTP_422_UNPROCESSABLE_CONTENT,
    "주민번호·계좌번호 등 민감정보는 제공하지 않습니다. 입력 시에도 자동 차단됩니다.",
)


def require_mentor(user: AuthenticatedUser) -> CurrentUser:
    if user.role != Role.MENTOR:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")
    return user


Mentor = Annotated[CurrentUser, Depends(require_mentor)]


def _out(s: Share, now: datetime) -> ShareOut:
    return ShareOut(
        id=s.id, resume_id=s.resume_id, mentor_id=s.shared_with, mentor_label=s.mentor_label,
        end_date=period.end_date_of(s.expires_at),
        expires_at=s.expires_at, status=service.status_of(s, now), created_at=s.created_at,
        revoked_at=s.revoked_at,
    )


def _share_or_404(db: Session, owner_id: str, share_id: uuid.UUID) -> Share:
    s = repo.get_for_owner(db, owner_id, share_id)
    if s is None:
        raise _NOT_FOUND
    return s


# --- 소유자 ----------------------------------------------------------------

@owner_router.post("/resumes/{resume_id}/shares", response_model=ShareOut, status_code=status.HTTP_201_CREATED)
def create_share(resume_id: uuid.UUID, payload: ShareCreate, user: AuthenticatedUser, db: Db):
    ensure_user(db, user.sub)
    now = datetime.now(UTC)
    try:
        share = service.create_share(db, user.sub, resume_id, payload.mentor_id, payload.end_date,
                                     mentor_label=payload.mentor_label, confirm=payload.confirm, now=now)
    except service.ShareConfirmRequired as e:
        raise ConflictError(e.message, code="share_confirm_required", errors={"kind": e.kind}) from None
    except period.PeriodInvalid:
        raise _PERIOD from None
    except pii_hooks.SensitiveInputBlocked:
        raise _SENSITIVE from None
    except service.SelfShare:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "본인에게는 공유할 수 없습니다.") from None
    except service.MentorNotFound:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "공유할 멘토를 찾을 수 없습니다.") from None
    except service.NothingToShare:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "공유할 내용이 없습니다. 문항에 내용을 저장한 뒤 공유해 주세요."
        ) from None
    if share is None:
        raise _NOT_FOUND
    return _out(share, now)


@owner_router.get("/resumes/{resume_id}/shares", response_model=list[ShareOut])
def list_shares(resume_id: uuid.UUID, user: AuthenticatedUser, db: Db):
    if repo.lock_resume(db, user.sub, resume_id) is None:
        raise _NOT_FOUND
    now = datetime.now(UTC)
    return [_out(s, now) for s in repo.list_for_owner(db, user.sub, resume_id)]


@owner_router.post("/shares/{share_id}/extend", response_model=ShareOut)
def extend_share(share_id: uuid.UUID, payload: ShareExtend, user: AuthenticatedUser, db: Db):
    s = _share_or_404(db, user.sub, share_id)
    now = datetime.now(UTC)
    try:
        service.extend_share(db, s, payload.end_date, now=now)
    except service.ShareEnded:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "만료되었거나 취소된 공유는 연장할 수 없습니다. 새로 공유해 주세요."
        ) from None
    except period.PeriodInvalid:
        raise _PERIOD from None
    except service.ExtendNotLater:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "연장 종료일은 현재 종료일보다 뒤여야 합니다."
        ) from None
    return _out(s, now)


@owner_router.patch("/shares/{share_id}", response_model=ShareOut)
def rename_share(share_id: uuid.UUID, payload: ShareRename, user: AuthenticatedUser, db: Db):
    """멘토 별칭 수정. 끝난 공유도 가능(작성자 본인 메모)."""
    s = _share_or_404(db, user.sub, share_id)
    try:
        service.rename_share(db, s, payload.mentor_label)
    except pii_hooks.SensitiveInputBlocked:
        raise _SENSITIVE from None
    return _out(s, datetime.now(UTC))


@owner_router.delete("/shares/{share_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_share(share_id: uuid.UUID, user: AuthenticatedUser, db: Db):
    service.revoke_share(db, _share_or_404(db, user.sub, share_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- 멘토 (읽기 전용) -------------------------------------------------------

@mentor_router.get("", response_model=list[ReceivedShare])
def received_shares(user: Mentor, db: Db):
    rows = repo.list_for_mentor(db, user.sub, datetime.now(UTC))
    return [ReceivedShare(id=s.id, resume_title=title, end_date=period.end_date_of(s.expires_at))
            for s, title in rows]


@mentor_router.get("/{share_id}", response_model=SharedResume)
def view_shared(share_id: uuid.UUID, user: Mentor, db: Db):
    row = repo.get_for_mentor(db, user.sub, share_id, datetime.now(UTC))
    if row is None:
        raise _NOT_FOUND
    share, resume = row
    items = [
        SharedQuestion(question_title=q.title, char_limit=q.char_limit, version_no=v.version_no, body=v.body)
        for v, q in repo.shared_versions(db, share.version_ids)
    ]
    return SharedResume(id=share.id, resume_title=resume.title,
                        end_date=period.end_date_of(share.expires_at), questions=items)
