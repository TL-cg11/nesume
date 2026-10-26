"""멘토 공유 (tasks B10, spec 3.7, part2_guide 4.40).

- 공유 시점의 문항별 최신 버전을 고정한다. 이후 수정본은 멘토에게 보이지 않는다
- 같은 멘토에게 유효한 공유가 있으면 확인을 받는다(ShareConfirmRequired). 확인 후:
  같은 자소서면 기존 공유를 종료하고 새로 만들고, 다른 자소서면 기존 공유는 그대로 둔다
- 취소는 만료와 같게 본다. 끝난 공유는 되살리지 않고 다시 공유하면 새로 만든다
- 연장은 유효한 공유만. 연장일을 1일째로 30일째 날까지, 현재 종료일보다 뒤
- 변경마다 resumes.shared_with와 벡터 메타데이터를 같은 트랜잭션에서 갱신한다
"""
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.features.resumes import pii_hooks
from app.features.resumes import repository as resume_repo
from app.features.resumes.service import ensure_user
from app.features.share import index_hooks, period
from app.features.share import repository as repo
from app.models import Resume, Share


class NothingToShare(ValueError):
    """저장된 버전이 하나도 없는 자소서."""


class MentorNotFound(ValueError):
    """탈퇴(삭제 처리)한 계정."""


class SelfShare(ValueError):
    pass


class ShareEnded(ValueError):
    """만료·취소된 공유는 연장할 수 없다."""


class ExtendNotLater(ValueError):
    pass


@dataclass
class ShareConfirmRequired(Exception):
    kind: str  # same_content / older_version / other_resume
    message: str


def status_of(s: Share, now: datetime) -> str:
    if s.revoked_at is not None:
        return "revoked"
    return "active" if s.expires_at > now else "expired"


def _latest_version_ids(db: Session, owner_id: str, resume_id: uuid.UUID) -> list[uuid.UUID]:
    questions = resume_repo.list_questions(db, owner_id, resume_id)
    latest = resume_repo.latest_versions(db, [q.id for q in questions])
    return [latest[q.id].id for q in questions if q.id in latest]


def _confirm_message(kind: str, existing: Share | None) -> str:
    if kind == "other_resume":
        return "이 멘토에게 다른 자소서가 공유되어 있습니다. 기존 공유와 별개로 이 자소서를 공유할까요?"
    end = period.end_date_of(existing.expires_at).strftime("%Y-%m-%d")
    if kind == "same_content":
        return (f"이 멘토에게 같은 내용의 자소서가 이미 공유되어 있습니다({end}까지). "
                "기존 공유를 종료하고 새로 공유할까요?")
    return (f"이 멘토에게 이 자소서의 이전 버전이 공유되어 있습니다({end}까지). "
            "기존 공유를 종료하고 현재 버전으로 새로 공유할까요?")


def sync_resume(db: Session, resume: Resume, now: datetime) -> None:
    """원본(shares) → resumes.shared_with 복제본 → 벡터 메타데이터."""
    shared = [
        {"user_id": s.shared_with, "expires_at": period.iso_z(s.expires_at)}
        for s in repo.active_for_resume(db, resume.id, now)
    ]
    resume.shared_with = shared
    db.flush()
    index_hooks.sync_shared_with(db, resume.id, shared)


def create_share(
    db: Session, owner_id: str, resume_id: uuid.UUID, mentor_id: str, end: date | None,
    *, mentor_label: str, confirm: bool = False, now: datetime | None = None,
) -> Share | None:
    """공유 생성. 자소서가 없거나 타인 소유면 None."""
    now = now or datetime.now(UTC)
    resume = repo.lock_resume(db, owner_id, resume_id)
    if resume is None:
        return None
    if mentor_id == owner_id:
        raise SelfShare()
    mentor = repo.get_user(db, mentor_id)
    if mentor is not None and mentor.deleted_at is not None:
        raise MentorNotFound()
    # 멘토가 아직 B 기능을 쓴 적이 없으면 users 행이 없다. 공유 시 만든다(part2_guide 4.40).
    # 잘못 입력한 ID는 로그인할 수 없는 계정이라 열람되지 않는다. D7 로그인 시 생성 도입 시 검증으로 교체
    if mentor is None:
        ensure_user(db, mentor_id)
    end = end or period.default_end(now)
    period.check_end(end, now)
    pii_hooks.ensure_no_sensitive(mentor_label)
    version_ids = _latest_version_ids(db, owner_id, resume_id)
    if not version_ids:
        raise NothingToShare()

    existing = repo.active_for_mentor(db, owner_id, mentor_id, now)
    same = [s for s in existing if s.resume_id == resume_id]
    if existing and not confirm:
        if same:
            kind = "same_content" if list(same[0].version_ids) == version_ids else "older_version"
            raise ShareConfirmRequired(kind, _confirm_message(kind, same[0]))
        raise ShareConfirmRequired("other_resume", _confirm_message("other_resume", None))
    for s in same:
        s.revoked_at = now

    share = Share(resume_id=resume_id, owner_id=owner_id, shared_with=mentor_id, mentor_label=mentor_label,
                  expires_at=period.expires_at_for(end), version_ids=version_ids)
    db.add(share)
    db.flush()
    sync_resume(db, resume, now)
    db.refresh(share)
    return share


def extend_share(db: Session, share: Share, end: date, *, now: datetime | None = None) -> Share:
    now = now or datetime.now(UTC)
    if status_of(share, now) != "active":
        raise ShareEnded()
    period.check_end(end, now)
    if end <= period.end_date_of(share.expires_at):
        raise ExtendNotLater()
    share.expires_at = period.expires_at_for(end)
    db.flush()
    sync_resume(db, db.get(Resume, share.resume_id), now)
    return share


def revoke_share(db: Session, share: Share, *, now: datetime | None = None) -> None:
    """취소. 이미 끝난 공유는 그대로 둔다(멱등)."""
    now = now or datetime.now(UTC)
    if status_of(share, now) == "active":
        share.revoked_at = now
        db.flush()
        sync_resume(db, db.get(Resume, share.resume_id), now)


def rename_share(db: Session, share: Share, mentor_label: str) -> Share:
    """별칭 수정. 작성자 본인 메모라 끝난 공유도 고칠 수 있다."""
    pii_hooks.ensure_no_sensitive(mentor_label)
    share.mentor_label = mentor_label
    db.flush()
    return share


def _tag(s: Share, now: datetime) -> dict:
    status = status_of(s, now)
    ended_on = None
    if status == "revoked":
        ended_on = s.revoked_at.astimezone(period.KST).date()
    elif status == "expired":
        ended_on = period.end_date_of(s.expires_at)
    return {"share_id": s.id, "mentor_label": s.mentor_label, "end_date": period.end_date_of(s.expires_at),
            "status": status, "ended_on": ended_on}


def version_tags(
    db: Session, owner_id: str, version_ids: list[uuid.UUID], *, include_ended: bool = False,
    now: datetime | None = None,
) -> dict[uuid.UUID, list[dict]]:
    """버전별 공유 태그(작성자 화면용). 유효한 공유를 앞에, 종료일 빠른 순."""
    now = now or datetime.now(UTC)
    wanted = set(version_ids)
    out: dict[uuid.UUID, list[dict]] = {v: [] for v in version_ids}
    for s in repo.for_owner_versions(db, owner_id, version_ids, now, include_ended=include_ended):
        for vid in set(s.version_ids) & wanted:
            out[vid].append(_tag(s, now))
    for tags in out.values():
        tags.sort(key=lambda t: (t["status"] != "active", t["end_date"]))
    return out


def resume_summaries(
    db: Session, owner_id: str, resume_ids: list[uuid.UUID], *, now: datetime | None = None,
) -> dict[uuid.UUID, dict]:
    """자소서별 유효한 공유 요약: 멘토 수, 가장 빠른 종료일. 공유가 없으면 키 없음."""
    now = now or datetime.now(UTC)
    out: dict[uuid.UUID, dict] = {}
    for s in repo.active_for_resumes(db, owner_id, resume_ids, now):
        end = period.end_date_of(s.expires_at)
        cur = out.setdefault(s.resume_id, {"active_count": 0, "earliest_end_date": end})
        cur["active_count"] += 1
        cur["earliest_end_date"] = min(cur["earliest_end_date"], end)
    return out
