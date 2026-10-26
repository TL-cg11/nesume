"""삭제 배치 + 계정 삭제 (tasks B20, spec 3.1·3.5·10.2, part2_guide 4.49).

문서 물리 삭제: 소프트 삭제 후 30일이 지난 자소서·문항·경험을 지운다.
  자소서 → 문항·버전·공유·코멘트(DB 연쇄) + 검색 임베딩(C3) + 대응표(B7)
  문항   → 버전(DB 연쇄) + 대응표. 검색 청크는 자소서 재인덱싱 대상(Embedder 확정 후, 4.42)
  경험   → 문항 연결(DB 연쇄) + 검색 임베딩 + 대응표
계정 삭제: 요청 시 users.deleted_at에 기록(30일 유예, 이 기간에 철회 가능). 30일 뒤 배치가
  감사 로그 user_id 익명화 → S3 users/{id}/ 삭제 → 데이터 키 폐기 → 사용자 행 삭제(소유 데이터 DB 연쇄)
  → 이 사용자가 멘토로 받은 공유가 사라졌으므로 작성자 자소서의 공유 복제본·검색 메타 재동기화.

B는 함수만 제공한다. 요청·철회 API와 유예 중 로그인 차단, Cognito 사용자 삭제는 D(D7) 영역.
배치는 종류별 1회 최대 100건, 오래된 순. 건마다 커밋해 한 건 실패가 나머지를 막지 않는다.
"""
import logging
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.storage import objects
from app.features.share import service as share_service
from app.models import AuditLog, Experience, Question, Resume, Share, ShareComment, User, Version
from app.pii import envelope
from app.pii.pg_vault_store import delete_in
from app.retrieval import indexing

log = logging.getLogger("nesume.deletion")

GRACE = timedelta(days=30)
BATCH = 100


@dataclass
class PurgeResult:
    resumes: int = 0
    questions: int = 0
    experiences: int = 0
    accounts: int = 0
    failed: list[str] = field(default_factory=list)  # "종류:id" (내용 없음)


# --- 계정 삭제 요청·철회 (D7 API가 호출) ---------------------------------------

def request_account_deletion(db: Session, user_id: str, *, now: datetime | None = None) -> datetime:
    """삭제 예약. 이미 예약돼 있으면 처음 시각을 유지한다. 완전 삭제 예정 시각을 돌려준다."""
    now = now or datetime.now(UTC)
    u = db.get(User, user_id)
    if u is None:
        db.add(u := User(id=user_id))
    if u.deleted_at is None:
        u.deleted_at = now
    db.flush()
    return u.deleted_at + GRACE


def cancel_account_deletion(db: Session, user_id: str) -> bool:
    """유예 기간 안이면 철회(True). 예약이 없으면 False."""
    u = db.get(User, user_id)
    if u is None or u.deleted_at is None:
        return False
    u.deleted_at = None
    db.flush()
    return True


def deletion_pending(db: Session, user_id: str) -> bool:
    """삭제 예약 중인 계정인가. D7이 로그인·요청 차단에 쓴다."""
    u = db.get(User, user_id)
    return u is not None and u.deleted_at is not None


# --- 공통 -------------------------------------------------------------------

def _vaults(*groups) -> set[str]:
    return {v for g in groups for v in g if v}


def _drop_vaults(db: Session, vault_ids: set[str]) -> None:
    """참조하던 행을 지운 뒤 대응표를 지운다(FK NO ACTION, 4.33)."""
    db.flush()
    for vid in vault_ids:
        delete_in(db, vid)
    db.flush()


def _due(model, now: datetime, batch: int, *extra):
    return (select(model).where(model.deleted_at.is_not(None), model.deleted_at <= now - GRACE, *extra)
            .order_by(model.deleted_at).limit(batch))


# --- 문서 물리 삭제 -------------------------------------------------------------

def purge_resume(db: Session, r: Resume) -> None:
    version_vaults = db.scalars(select(Version.vault_id).join(Question).where(Question.resume_id == r.id)).all()
    comment_vaults = db.scalars(
        select(ShareComment.vault_id).join(Share).where(Share.resume_id == r.id)).all()
    indexing.delete_personal(db, source_id=r.id)
    db.delete(r)
    _drop_vaults(db, _vaults(version_vaults, comment_vaults))


def purge_question(db: Session, q: Question) -> None:
    vaults = db.scalars(select(Version.vault_id).where(Version.question_id == q.id)).all()
    db.delete(q)
    _drop_vaults(db, _vaults(vaults))


def purge_experience(db: Session, e: Experience) -> None:
    vault = e.vault_id
    indexing.delete_personal(db, source_id=e.id)
    db.delete(e)
    _drop_vaults(db, _vaults([vault]))


# --- 계정 완전 삭제 -------------------------------------------------------------

def purge_account(db: Session, user_id: str) -> None:
    u = db.get(User, user_id)
    if u is None:
        return
    # 1) 감사 로그 익명화(spec 10.2). B11 트리거는 users.anon_id에 있는 값으로 바꾸는 것만 허용하므로 행 삭제 전에
    if u.anon_id is None:
        u.anon_id = f"anon-{secrets.token_hex(16)}"
        db.flush()
    db.execute(update(AuditLog).where(AuditLog.user_id == user_id).values(user_id=u.anon_id))
    # 2) 이 사용자가 멘토로 받은 공유 → 행 삭제 후 작성자 자소서 복제본·검색 메타를 다시 맞춘다
    shared_resumes = set(db.scalars(select(Share.resume_id).where(Share.shared_with == user_id)).all())
    # 3) 파일(S3)은 DB보다 먼저: DB 삭제가 실패해도 다음 배치가 다시 지울 수 있다(멱등)
    objects.delete_user_objects(user_id)
    # 4) 데이터 키 폐기 → 백업에 남은 대응표도 복호화 불가
    envelope.destroy_user_key(db, user_id)
    # 5) 사용자 행 삭제 → 소유 데이터 전부 DB 연쇄 삭제(자소서·경험·대응표·임베딩·공유·코멘트·지원 기록 등)
    db.delete(u)
    db.flush()
    now = datetime.now(UTC)
    for rid in shared_resumes:
        r = db.get(Resume, rid)
        if r is not None:
            share_service.sync_resume(db, r, now)


# --- 배치 -------------------------------------------------------------------

def run(db_factory, *, now: datetime | None = None, batch: int = BATCH) -> PurgeResult:
    """한 번 실행. db_factory()는 새 세션을 돌려준다(건마다 별도 트랜잭션)."""
    now = now or datetime.now(UTC)
    res = PurgeResult()

    def each(kind: str, ids: list, load, purge, counter: str):
        for i in ids:
            try:
                with db_factory() as db, db.begin():
                    obj = load(db, i)
                    if obj is not None:
                        purge(db, obj)
                setattr(res, counter, getattr(res, counter) + 1)
            except Exception:
                log.exception("purge_failed", extra={"fields": {"kind": kind, "id": str(i)}})
                res.failed.append(f"{kind}:{i}")

    with db_factory() as db:
        resume_ids = db.scalars(_due(Resume, now, batch).with_only_columns(Resume.id)).all()
        question_ids = db.scalars(_due(Question, now, batch).with_only_columns(Question.id)).all()
        exp_ids = db.scalars(_due(Experience, now, batch).with_only_columns(Experience.id)).all()
        user_ids = db.scalars(_due(User, now, batch).with_only_columns(User.id)).all()

    each("resume", resume_ids, lambda db, i: db.get(Resume, i), purge_resume, "resumes")
    each("question", question_ids, lambda db, i: db.get(Question, i), purge_question, "questions")
    each("experience", exp_ids, lambda db, i: db.get(Experience, i), purge_experience, "experiences")
    each("account", user_ids, lambda db, i: i, purge_account, "accounts")
    log.info("purge_done", extra={"fields": {
        "resumes": res.resumes, "questions": res.questions, "experiences": res.experiences,
        "accounts": res.accounts, "failed": len(res.failed)}})
    return res


def main() -> int:
    """D5 CronJob 진입점: `python -m app.features.deletion.service`. 실패가 있으면 1."""
    from app.db import SessionLocal

    res = run(SessionLocal)
    print(f"resumes={res.resumes} questions={res.questions} experiences={res.experiences} "
          f"accounts={res.accounts} failed={len(res.failed)}")
    return 1 if res.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
