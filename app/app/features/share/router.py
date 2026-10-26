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
from app.features.resumes.service import ensure_user, restore_body as service_restore
from app.features.share import comments, display, period, service
from app.features.share import repository as repo
from app.features.share.schemas import (
    CommentCreate, CommentEdit, MentorComment, OwnerComment, ReceivedShare, SharedQuestion, SharedResume,
    ShareCreate, ShareExtend, ShareOut, ShareRename,
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


def _out(s: Share, now: datetime, count: tuple[int, int] = (0, 0)) -> ShareOut:
    return ShareOut(
        comment_count=count[0], unread_count=count[1],
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
    rows = repo.list_for_owner(db, user.sub, resume_id)
    n = comments.counts(db, [s.id for s in rows])
    return [_out(s, now, n.get(s.id, (0, 0))) for s in rows]


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


@owner_router.get("/shares/{share_id}/comments", response_model=list[OwnerComment])
def owner_comments(share_id: uuid.UUID, user: AuthenticatedUser, db: Db):
    """멘토 코멘트(원문). 공유가 끝나도 작성자는 볼 수 있다(4.47)."""
    s = _share_or_404(db, user.sub, share_id)
    rows = comments.list_for_share(db, s.id)
    versions = {v.id: (v, q) for v, q in repo.shared_versions(db, s.version_ids)}
    out = []
    for c in rows:
        v, q = versions.get(c.version_id, (None, None))
        para = None
        if v is not None:
            raw = service_restore(db, user.sub, user.sub, v)
            parts = comments.paragraphs(raw)
            para = parts[c.paragraph_index] if c.paragraph_index < len(parts) else None
        out.append(OwnerComment(
            id=c.id, version_id=c.version_id, question_title=q.title if q else None,
            paragraph_index=c.paragraph_index, paragraph=para, body=comments.for_owner(db, user.sub, c),
            read_at=c.read_at, created_at=c.created_at, updated_at=c.updated_at,
        ))
    return out


@owner_router.post("/shares/{share_id}/comments/{comment_id}/read", response_model=OwnerComment)
def mark_comment_read(share_id: uuid.UUID, comment_id: uuid.UUID, user: AuthenticatedUser, db: Db):
    s = _share_or_404(db, user.sub, share_id)
    c = comments.get_in_share(db, s.id, comment_id)
    if c is None:
        raise _NOT_FOUND
    comments.mark_read(db, c)
    return next(x for x in owner_comments(share_id, user, db) if x.id == c.id)


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
    by_version: dict[uuid.UUID, list[MentorComment]] = {}
    for c in comments.list_for_share(db, share.id):
        by_version.setdefault(c.version_id, []).append(MentorComment(
            id=c.id, version_id=c.version_id, paragraph_index=c.paragraph_index, body=comments.for_mentor(c),
            created_at=c.created_at, updated_at=c.updated_at))
    items = [
        SharedQuestion(question_title=q.title, char_limit=q.char_limit, version_id=v.id, version_no=v.version_no,
                       body=display.readable(v.body),
                       paragraphs=[display.readable(p) for p in comments.paragraphs(v.body)],
                       comments=by_version.get(v.id, []))
        for v, q in repo.shared_versions(db, share.version_ids)
    ]
    return SharedResume(id=share.id, resume_title=resume.title,
                        end_date=period.end_date_of(share.expires_at), questions=items)


def _active_share_for_mentor(db: Session, mentor_id: str, share_id: uuid.UUID) -> Share:
    row = repo.get_for_mentor(db, mentor_id, share_id, datetime.now(UTC))
    if row is None:
        raise _NOT_FOUND
    return row[0]


_TARGET = HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "코멘트를 남길 문단을 찾을 수 없습니다.")


def _mentor_out(c) -> MentorComment:
    return MentorComment(id=c.id, version_id=c.version_id, paragraph_index=c.paragraph_index,
                         body=comments.for_mentor(c), created_at=c.created_at, updated_at=c.updated_at)


@mentor_router.post("/{share_id}/comments", response_model=MentorComment, status_code=status.HTTP_201_CREATED)
def add_comment(share_id: uuid.UUID, payload: CommentCreate, user: Mentor, db: Db):
    """문단별 코멘트(B17). 유효한 공유에서만. 본문은 바꿀 수 없다."""
    share = _active_share_for_mentor(db, user.sub, share_id)
    try:
        c = comments.add(db, share, payload.version_id, payload.paragraph_index, payload.body)
    except comments.TargetInvalid:
        raise _TARGET from None
    except pii_hooks.SensitiveInputBlocked:
        raise _SENSITIVE from None
    return _mentor_out(c)


def _own_comment(db: Session, mentor_id: str, share_id: uuid.UUID, comment_id: uuid.UUID):
    share = _active_share_for_mentor(db, mentor_id, share_id)
    c = comments.get_in_share(db, share.id, comment_id)
    if c is None:
        raise _NOT_FOUND
    return c


@mentor_router.patch("/{share_id}/comments/{comment_id}", response_model=MentorComment)
def edit_comment(share_id: uuid.UUID, comment_id: uuid.UUID, payload: CommentEdit, user: Mentor, db: Db):
    c = _own_comment(db, user.sub, share_id, comment_id)
    try:
        comments.edit(db, c, payload.body)
    except pii_hooks.SensitiveInputBlocked:
        raise _SENSITIVE from None
    return _mentor_out(c)


@mentor_router.delete("/{share_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(share_id: uuid.UUID, comment_id: uuid.UUID, user: Mentor, db: Db):
    comments.remove(db, _own_comment(db, user.sub, share_id, comment_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
