"""멘토 문단별 코멘트 (tasks B17, part2_guide 4.47).

- 문단: 공유 시점 버전 본문을 빈 줄로 나눈다(0부터). 버전이 고정이라 번호가 어긋나지 않는다
- 멘토: 유효한 공유에서만 쓰기·수정·삭제. 자기 코멘트만 고칠 수 있다
- 작성자: 공유가 끝나도 읽을 수 있고 확인 표시만 한다(답글 없음)
- 본문은 민감정보 거부 + 토큰화(대응표는 작성자 소유). 작성자에게는 원문, 멘토에게는 비공개 문구
"""
import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.features.resumes import pii_hooks
from app.features.share import display
from app.models import Share, ShareComment, Version

MAX_LEN = 1000
_BLANK_LINE = re.compile(r"\n[ \t]*\n")


class TargetInvalid(ValueError):
    """공유에 고정되지 않은 버전이거나 없는 문단."""


def paragraphs(text: str) -> list[str]:
    """빈 줄 기준 문단. 앞뒤 공백을 지우고 빈 문단은 뺀다. 빈 줄이 없으면 전체가 한 문단."""
    return [p.strip() for p in _BLANK_LINE.split(text.replace("\r\n", "\n")) if p.strip()]


def _check_target(db: Session, share: Share, version_id: uuid.UUID, paragraph_index: int) -> None:
    if version_id not in set(share.version_ids):
        raise TargetInvalid()
    v = db.get(Version, version_id)
    if v is None or not 0 <= paragraph_index < len(paragraphs(v.body)):
        raise TargetInvalid()


def add(db: Session, share: Share, version_id: uuid.UUID, paragraph_index: int, body: str) -> ShareComment:
    _check_target(db, share, version_id, paragraph_index)
    protected, vault_id = pii_hooks.protect_fields(db, share.owner_id, {"body": body})
    c = ShareComment(share_id=share.id, owner_id=share.owner_id, version_id=version_id,
                     paragraph_index=paragraph_index, body=protected["body"], vault_id=vault_id)
    db.add(c)
    db.flush()
    db.refresh(c)
    return c


def edit(db: Session, c: ShareComment, body: str) -> ShareComment:
    old_vault = c.vault_id
    protected, c.vault_id = pii_hooks.protect_fields(db, c.owner_id, {"body": body})
    c.body = protected["body"]
    db.flush()
    pii_hooks.discard_vault(db, old_vault)
    db.refresh(c)
    return c


def remove(db: Session, c: ShareComment) -> None:
    vault = c.vault_id
    db.delete(c)
    db.flush()
    pii_hooks.discard_vault(db, vault)


def get_in_share(db: Session, share_id: uuid.UUID, comment_id: uuid.UUID) -> ShareComment | None:
    return db.scalar(select(ShareComment).where(ShareComment.id == comment_id, ShareComment.share_id == share_id))


def list_for_share(db: Session, share_id: uuid.UUID) -> list[ShareComment]:
    return list(db.scalars(
        select(ShareComment).where(ShareComment.share_id == share_id)
        .order_by(ShareComment.version_id, ShareComment.paragraph_index, ShareComment.created_at)
    ).all())


def for_mentor(c: ShareComment) -> str:
    return display.readable(c.body)


def for_owner(db: Session, owner_id: str, c: ShareComment) -> str:
    return pii_hooks.restore_fields(db, owner_id, owner_id, {"body": c.body}, c.vault_id)["body"]


def mark_read(db: Session, c: ShareComment) -> ShareComment:
    if c.read_at is None:
        c.read_at = datetime.now(UTC)
        db.flush()
    return c


def counts(db: Session, share_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[int, int]]:
    """공유별 (코멘트 수, 확인 안 한 수)."""
    if not share_ids:
        return {}
    rows = db.execute(
        select(ShareComment.share_id, func.count(), func.count().filter(ShareComment.read_at.is_(None)))
        .where(ShareComment.share_id.in_(share_ids))
        .group_by(ShareComment.share_id)
    ).all()
    return {sid: (total, unread) for sid, total, unread in rows}
