"""B20 삭제 배치 + 계정 삭제 (part2_guide 4.49). 잔존 0건 확인."""
import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from botocore.exceptions import ClientError
from sqlalchemy import func, select, update

from app import aws
from app.config import get_settings
from app.core.storage import objects
from app.db import SessionLocal
from app.features.deletion import service as deletion
from app.features.experiences import index_hooks as exp_index
from app.features.experiences import service as exp_service
from app.features.resumes import service as resume_service
from app.features.share import comments as share_comments
from app.features.share import service as share_service
from app.models import (
    AuditLog, Experience, PiiVault, Question, Resume, Share, ShareComment, User, UserKey,
    UserProfileEmbedding, Version,
)
from app.models.embedding import EMBED_DIM

PII = "010-1234-5678"
VEC = [1.0] + [0.0] * (EMBED_DIM - 1)
NOW = datetime.now(UTC)


@pytest.fixture(autouse=True)
def _no_live_index(monkeypatch):
    monkeypatch.setattr(exp_index, "index_experience", lambda *a, **k: None)


def _uid(p="b20"):
    return f"{p}-{uuid.uuid4().hex[:8]}"


def _emb(db, owner, kind, source_id):
    db.add(UserProfileEmbedding(owner_id=owner, source_type=kind, source_id=source_id, content="x", embedding=VEC))


def _resume(db, owner, body=f"연락처 {PII}"):
    r = resume_service.create_resume(db, owner, title="t")
    q = resume_service.create_question(db, r, "문항", None, 0)
    resume_service.create_version(db, owner, r.id, q.id, body, "manual")
    _emb(db, owner, "resume", r.id)
    db.flush()
    return r, q


def _age(model, pk, days):
    with SessionLocal.begin() as db:
        db.execute(update(model).where(model.__mapper__.primary_key[0] == pk)
                   .values(deleted_at=NOW - timedelta(days=days)))


def _count(model, *where):
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(model).where(*where))


def _run():
    return deletion.run(SessionLocal, now=NOW)


# --- 문서 물리 삭제 -------------------------------------------------------------

@pytest.mark.parametrize("days,purged", [(29, False), (30, True)])
def test_resume_purged_after_30_days_with_everything(days, purged):
    owner, mentor = _uid(), _uid()
    with SessionLocal.begin() as db:
        r, q = _resume(db, owner)
        db.add(User(id=mentor))
        db.flush()
        s = share_service.create_share(db, owner, r.id, mentor, None, mentor_label="멘토")
        v = db.scalar(select(Version).where(Version.question_id == q.id))
        share_comments.add(db, s, v.id, 0, f"연락처 {PII} 빼세요")
        resume_service.soft_delete_resume(db, r)
        rid, vault_ids = r.id, [v.vault_id, db.scalar(select(ShareComment.vault_id).where(ShareComment.share_id == s.id))]
    _age(Resume, rid, days)
    res = _run()
    left = 0 if purged else 1
    assert res.resumes == (1 if purged else 0) and not res.failed
    assert _count(Resume, Resume.id == rid) == left
    assert _count(Question, Question.resume_id == rid) == left
    assert _count(Share, Share.resume_id == rid) == left
    assert _count(UserProfileEmbedding, UserProfileEmbedding.source_id == rid) == left
    assert _count(PiiVault, PiiVault.id.in_(vault_ids)) == (0 if purged else 2)


def test_question_purge_drops_versions_and_vaults():
    owner = _uid()
    with SessionLocal.begin() as db:
        r, q = _resume(db, owner)
        resume_service.soft_delete_question(db, q)
        qid, vault = q.id, db.scalar(select(Version.vault_id).where(Version.question_id == q.id))
    _age(Question, qid, 31)
    assert _run().questions == 1
    assert _count(Version, Version.question_id == qid) == 0
    assert _count(PiiVault, PiiVault.id == vault) == 0
    assert _count(Resume, Resume.owner_id == owner) == 1  # 자소서는 그대로


def test_experience_purge_drops_embedding_and_vault():
    owner = _uid()
    with SessionLocal.begin() as db:
        e = exp_service.create_experience(db, owner, {"title": f"제목 {PII}", "type": "x"})
        _emb(db, owner, "experience", e.id)
        exp_service.soft_delete_experience(db, e)
        eid, vault = e.id, e.vault_id
    _age(Experience, eid, 30)
    assert _run().experiences == 1
    assert _count(Experience, Experience.id == eid) == 0
    assert _count(UserProfileEmbedding, UserProfileEmbedding.source_id == eid) == 0
    assert _count(PiiVault, PiiVault.id == vault) == 0


def test_batch_limit_oldest_first(monkeypatch):
    owner = _uid()
    ids = []
    with SessionLocal.begin() as db:
        for _ in range(3):
            e = exp_service.create_experience(db, owner, {"title": "t", "type": "x"})
            exp_service.soft_delete_experience(db, e)
            ids.append(e.id)
    for i, eid in enumerate(ids):
        _age(Experience, eid, 40 - i)  # ids[0]이 가장 오래됨
    res = deletion.run(SessionLocal, now=NOW, batch=2)
    assert res.experiences >= 2
    assert _count(Experience, Experience.id == ids[0]) == 0


def test_one_failure_does_not_block_others(monkeypatch):
    owner = _uid()
    with SessionLocal.begin() as db:
        e1 = exp_service.create_experience(db, owner, {"title": "a", "type": "x"})
        e2 = exp_service.create_experience(db, owner, {"title": "b", "type": "x"})
        for e in (e1, e2):
            exp_service.soft_delete_experience(db, e)
        bad, good = e1.id, e2.id
    _age(Experience, bad, 31)
    _age(Experience, good, 30)
    real = deletion.purge_experience
    monkeypatch.setattr(deletion, "purge_experience",
                        lambda db, e: (_ for _ in ()).throw(RuntimeError("x")) if e.id == bad else real(db, e))
    res = _run()
    assert f"experience:{bad}" in res.failed
    assert _count(Experience, Experience.id == good) == 0 and _count(Experience, Experience.id == bad) == 1


# --- 계정 삭제 -------------------------------------------------------------------

def _put(user_id, name="a.pdf"):
    key = objects.user_object_key(user_id, "files", name)
    objects.put_object(key, b"x", "application/pdf")
    return key


def _exists(key):
    try:
        aws.client("s3").head_object(Bucket=get_settings().s3_bucket_name, Key=key)
        return True
    except ClientError:
        return False


def test_request_cancel_and_pending():
    uid = _uid()
    with SessionLocal.begin() as db:
        due = deletion.request_account_deletion(db, uid, now=NOW)
        assert due == NOW + timedelta(days=30) and deletion.deletion_pending(db, uid)
        assert deletion.request_account_deletion(db, uid, now=NOW + timedelta(days=5)) == due  # 처음 시각 유지
        assert deletion.cancel_account_deletion(db, uid) and not deletion.deletion_pending(db, uid)
        assert not deletion.cancel_account_deletion(db, uid)


@pytest.mark.parametrize("days,purged", [(29, False), (30, True)])
def test_account_purge_after_grace(days, purged):
    uid, other = _uid(), _uid()
    with SessionLocal.begin() as db:
        r, _ = _resume(db, uid)
        e = exp_service.create_experience(db, uid, {"title": f"제목 {PII}", "type": "x"})
        _emb(db, uid, "experience", e.id)
        db.add(AuditLog(request_id=uuid.uuid4(), session_id="s", user_id=uid, role="user", feature="rewrite",
                        decision="allow", query_hash=hashlib.sha256(b"q").hexdigest()))
        db.add(AuditLog(request_id=uuid.uuid4(), session_id="s", user_id=other, role="user", feature="rewrite",
                        decision="allow", query_hash=hashlib.sha256(b"q").hexdigest()))
        deletion.request_account_deletion(db, uid, now=NOW - timedelta(days=days))
    key, other_key = _put(uid), _put(other)
    res = _run()
    if not purged:
        assert res.accounts == 0 and _count(User, User.id == uid) == 1 and _exists(key)
        return
    assert res.accounts == 1 and not res.failed
    # 잔존 0건: 사용자·문서·대응표·키·임베딩·파일
    for model, col in ((User, User.id), (Resume, Resume.owner_id), (Experience, Experience.owner_id),
                       (PiiVault, PiiVault.owner_id), (UserKey, UserKey.user_id),
                       (UserProfileEmbedding, UserProfileEmbedding.owner_id), (AuditLog, AuditLog.user_id)):
        assert _count(model, col == uid) == 0, model.__tablename__
    assert not _exists(key) and _exists(other_key)  # 다른 사용자 파일은 그대로
    # 감사 로그는 익명 토큰으로 보존(spec 10.2), 다른 사용자 로그는 그대로
    assert _count(AuditLog, AuditLog.user_id.like("anon-%"), AuditLog.feature == "rewrite") >= 1
    assert _count(AuditLog, AuditLog.user_id == other) == 1


def test_mentor_account_purge_resyncs_owner_share_replica(monkeypatch):
    owner, mentor = _uid(), _uid()
    synced = []
    monkeypatch.setattr(share_service.index_hooks, "sync_shared_with", lambda db, rid, sw: synced.append((rid, sw)))
    with SessionLocal.begin() as db:
        r, _ = _resume(db, owner)
        db.add(User(id=mentor))
        db.flush()
        share_service.create_share(db, owner, r.id, mentor, None, mentor_label="멘토")
        deletion.request_account_deletion(db, mentor, now=NOW - timedelta(days=30))
        rid = r.id
    assert _run().accounts == 1
    with SessionLocal() as db:
        assert db.get(Resume, rid).shared_with == []  # 작성자 자소서는 남고 공유 복제본만 정리
    assert synced[-1] == (rid, [])


def test_cancelled_account_not_purged():
    uid = _uid()
    with SessionLocal.begin() as db:
        deletion.request_account_deletion(db, uid, now=NOW - timedelta(days=40))
        deletion.cancel_account_deletion(db, uid)
    _run()
    assert _count(User, User.id == uid) == 1


def test_delete_user_objects_rejects_bad_id():
    with pytest.raises(ValueError):
        objects.delete_user_objects("../x")
