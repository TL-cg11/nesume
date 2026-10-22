"""B7 연결(마이그레이션 0011): 버전·경험 행의 대응표 참조와 삭제 순서."""
import uuid

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from app.features.experiences import index_hooks
from app.features.experiences import service as exp_service
from app.features.resumes import service as resume_service
from app.models import PiiVault, Question, Resume, User

PII = "010-1234-5678"


@pytest.fixture
def owner(db_session, monkeypatch):
    monkeypatch.setattr(index_hooks, "index_experience", lambda *a, **k: None)
    u = User(id=f"b7-{uuid.uuid4()}")
    db_session.add(u)
    db_session.flush()
    return u


def _version(db, owner_id):
    r = Resume(owner_id=owner_id, title="t")
    db.add(r)
    db.flush()
    q = Question(resume_id=r.id, owner_id=owner_id, title="문항")
    db.add(q)
    db.flush()
    version, _ = resume_service.create_version(db, owner_id, r.id, q.id, f"연락처 {PII}", "manual")
    return version


def test_referenced_vault_cannot_be_deleted_first(db_session, owner):
    v = _version(db_session, owner.id)
    with pytest.raises(IntegrityError):
        db_session.execute(delete(PiiVault).where(PiiVault.id == v.vault_id))
        db_session.flush()


def test_account_deletion_removes_documents_and_vaults(db_session, owner):
    v = _version(db_session, owner.id)
    e = exp_service.create_experience(db_session, owner.id, {"title": f"제목 {PII}", "type": "x"})
    vault_ids = [v.vault_id, e.vault_id]
    assert all(vault_ids)
    db_session.execute(delete(User).where(User.id == owner.id))
    db_session.flush()
    db_session.expire_all()
    assert all(db_session.get(PiiVault, vid) is None for vid in vault_ids)
