"""C4 공고 테이블 취합(마이그레이션 0010)과 자소서·지원 기록 공고 FK(C 결정 2)."""
import uuid

import pytest
from sqlalchemy import delete, inspect
from sqlalchemy.exc import IntegrityError

from app.db import engine
from app.models import Application, JobPosting, Resume, User


def _user(db):
    u = User(id=f"c4-{uuid.uuid4()}")
    db.add(u)
    db.flush()
    return u


def _posting(db, owner_user_id=None, source="seoul"):
    p = JobPosting(source=source, link_key=uuid.uuid4().hex * 2, content_hash=uuid.uuid4().hex * 2,
                   title="백엔드 개발자", owner_user_id=owner_user_id)
    db.add(p)
    db.flush()
    return p


def test_job_postings_table_exists():
    assert "job_postings" in inspect(engine).get_table_names()


@pytest.mark.parametrize("make_ref", [
    pytest.param(lambda db, u, p: Resume(owner_id=u.id, title="t", job_posting_id=p.id), id="resume"),
    pytest.param(lambda db, u, p: Application(owner_id=u.id, job_posting_id=p.id, status="applied"), id="application"),
])
def test_referenced_posting_cannot_be_deleted(db_session, make_ref):
    u = _user(db_session)
    p = _posting(db_session)
    db_session.add(make_ref(db_session, u, p))
    db_session.flush()
    with pytest.raises(IntegrityError):
        db_session.execute(delete(JobPosting).where(JobPosting.id == p.id))
        db_session.flush()


def test_unreferenced_posting_can_be_deleted(db_session):
    p = _posting(db_session)
    pid = p.id
    db_session.execute(delete(JobPosting).where(JobPosting.id == pid))
    db_session.flush()
    db_session.expire_all()
    assert db_session.get(JobPosting, pid) is None


def test_posting_deletable_after_reference_removed(db_session):
    u = _user(db_session)
    p = _posting(db_session)
    r = Resume(owner_id=u.id, title="t", job_posting_id=p.id)
    db_session.add(r)
    db_session.flush()
    db_session.execute(delete(Resume).where(Resume.id == r.id))  # 30일 후 물리 삭제(B20) 상황
    db_session.execute(delete(JobPosting).where(JobPosting.id == p.id))
    db_session.flush()


def test_account_deletion_with_own_posting_referenced_by_own_resume(db_session):
    # 사용자 입력 공고(owner_user_id CASCADE)를 같은 사용자의 자소서가 참조하는 상태에서 계정 삭제.
    # 공고와 자소서가 같은 문장에서 함께 지워져야 한다.
    u = _user(db_session)
    p = _posting(db_session, owner_user_id=u.id, source="user")
    db_session.add(Resume(owner_id=u.id, title="t", job_posting_id=p.id))
    db_session.add(Application(owner_id=u.id, job_posting_id=p.id, status="applied"))
    db_session.flush()
    pid = p.id
    db_session.execute(delete(User).where(User.id == u.id))
    db_session.flush()
    db_session.expire_all()
    assert db_session.get(JobPosting, pid) is None


def test_job_posting_defaults(db_session):
    p = _posting(db_session)
    db_session.refresh(p)
    assert p.grade == "public" and p.is_active is True and p.missing_streak == 0
