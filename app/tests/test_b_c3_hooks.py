"""B4·B5·B10 → C3 개인 인덱스 연동(part2_guide 4.39): 소프트 삭제·공유 변경이 같은 트랜잭션에서 반영된다."""
import uuid

import pytest
from sqlalchemy import select

from app.features.experiences import index_hooks as exp_index
from app.features.experiences import service as exp_service
from app.features.resumes import service as resume_service
from app.features.share import service as share_service
from app.models import Question, Resume, User, UserProfileEmbedding
from app.models.embedding import EMBED_DIM

VEC = [1.0] + [0.0] * (EMBED_DIM - 1)


@pytest.fixture(autouse=True)
def _no_live_index(monkeypatch):
    monkeypatch.setattr(exp_index, "index_experience", lambda *a, **k: None)


def _user(db):
    u = User(id=f"c3-{uuid.uuid4().hex[:8]}")
    db.add(u)
    db.flush()
    return u.id


def _emb(db, owner, source_type, source_id):
    e = UserProfileEmbedding(owner_id=owner, source_type=source_type, source_id=source_id, content="x",
                             embedding=VEC)
    db.add(e)
    db.flush()
    return e


def _resume_with_version(db, owner):
    r = Resume(owner_id=owner, title="t")
    db.add(r)
    db.flush()
    q = Question(resume_id=r.id, owner_id=owner, title="q")
    db.add(q)
    db.flush()
    resume_service.create_version(db, owner, r.id, q.id, "본문", "manual")
    return r


def _state(db, emb_id):
    db.expire_all()
    return db.scalar(select(UserProfileEmbedding).where(UserProfileEmbedding.id == emb_id))


def test_resume_soft_delete_marks_embeddings(db_session):
    owner = _user(db_session)
    r = _resume_with_version(db_session, owner)
    e = _emb(db_session, owner, "resume", r.id)
    resume_service.soft_delete_resume(db_session, r)
    assert _state(db_session, e.id).deleted_at == r.deleted_at


def test_experience_soft_delete_marks_embeddings(db_session):
    owner = _user(db_session)
    x = exp_service.create_experience(db_session, owner, {"title": "t", "type": "x"})
    e = _emb(db_session, owner, "experience", x.id)
    exp_service.soft_delete_experience(db_session, x)
    assert _state(db_session, e.id).deleted_at == x.deleted_at


def test_share_changes_sync_embedding_shared_with(db_session):
    owner, mentor = _user(db_session), _user(db_session)
    r = _resume_with_version(db_session, owner)
    e = _emb(db_session, owner, "resume", r.id)
    s = share_service.create_share(db_session, owner, r.id, mentor, None)
    got = _state(db_session, e.id).shared_with
    assert [x["user_id"] for x in got] == [mentor] and got[0]["expires_at"].endswith("Z")
    share_service.revoke_share(db_session, s)
    assert _state(db_session, e.id).shared_with == []
