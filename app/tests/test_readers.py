"""다른 팀용 읽기 함수(A11 요청): 소유자 범위, 소프트 삭제 제외, 원문 복원."""
import uuid
from datetime import UTC, datetime

import pytest

from app.features.experiences import index_hooks
from app.features.experiences import service as exp_service
from app.features.experiences.reader import linked_experiences_for_resume, list_owner_experiences
from app.features.resumes import service as resume_service
from app.features.resumes.reader import resume_bodies
from app.models import Question, Resume, User

PII = "010-1234-5678"


@pytest.fixture(autouse=True)
def _no_index(monkeypatch):
    monkeypatch.setattr(index_hooks, "index_experience", lambda *a, **k: None)


def _user(db):
    u = User(id=f"rd-{uuid.uuid4()}")
    db.add(u)
    db.flush()
    return u.id


def _resume_with(db, owner_id, bodies):
    r = Resume(owner_id=owner_id, title="t")
    db.add(r)
    db.flush()
    qs = []
    for i, body_list in enumerate(bodies):
        q = Question(resume_id=r.id, owner_id=owner_id, title=f"문항{i}", position=i)
        db.add(q)
        db.flush()
        for body in body_list:
            resume_service.create_version(db, owner_id, r.id, q.id, body, "manual")
        qs.append(q)
    return r, qs


def test_resume_bodies_latest_version_restored(db_session):
    owner = _user(db_session)
    r, qs = _resume_with(db_session, owner, [["초안", f"최종 {PII}"], []])
    got = resume_bodies(db_session, owner, r.id)
    assert [x["title"] for x in got] == ["문항0", "문항1"]
    assert got[0]["body"] == f"최종 {PII}"
    assert got[1]["body"] is None and got[1]["version_id"] is None


def test_resume_bodies_other_owner_and_deleted(db_session):
    owner, other = _user(db_session), _user(db_session)
    r, qs = _resume_with(db_session, owner, [["a"], ["b"]])
    assert resume_bodies(db_session, other, r.id) is None
    qs[1].deleted_at = datetime.now(UTC)
    db_session.flush()
    assert [x["title"] for x in resume_bodies(db_session, owner, r.id)] == ["문항0"]
    r.deleted_at = datetime.now(UTC)
    db_session.flush()
    assert resume_bodies(db_session, owner, r.id) is None


def test_list_owner_experiences_restored_and_scoped(db_session):
    owner, other = _user(db_session), _user(db_session)
    e = exp_service.create_experience(db_session, owner, {"title": f"제목 {PII}", "type": "x"})
    gone = exp_service.create_experience(db_session, owner, {"title": "삭제됨", "type": "x"})
    exp_service.soft_delete_experience(db_session, gone)
    exp_service.create_experience(db_session, other, {"title": "남의 것", "type": "x"})
    got = list_owner_experiences(db_session, owner)
    assert [x["id"] for x in got] == [e.id]
    assert got[0]["title"] == f"제목 {PII}"


@pytest.mark.parametrize("limit,offset", [(0, 0), (101, 0), (10, -1)])
def test_list_owner_experiences_bounds(db_session, limit, offset):
    with pytest.raises(ValueError):
        list_owner_experiences(db_session, "x", limit=limit, offset=offset)


# --- 자소서 → 끌어온 경험(C 요청 10/30) ---------------------------------------------

def test_linked_experiences_for_resume_order_dedupe_and_scope(db_session):
    owner, other = _user(db_session), _user(db_session)
    r, (q0, q1, q2) = _resume_with(db_session, owner, [[], [], []])
    e1 = exp_service.create_experience(db_session, owner, {"title": f"경험1 {PII}", "type": "프로젝트"})
    e2 = exp_service.create_experience(db_session, owner, {"title": "경험2", "type": "활동"})
    gone = exp_service.create_experience(db_session, owner, {"title": "삭제 경험", "type": "기타"})
    on_deleted_q = exp_service.create_experience(
        db_session, owner, {"title": "삭제 문항의 경험", "type": "기타"})
    exp_service.link(db_session, owner, q1.id, e2.id)
    exp_service.link(db_session, owner, q0.id, e1.id)
    exp_service.link(db_session, owner, q1.id, e1.id)          # 같은 경험이 두 문항에 → 한 번
    exp_service.link(db_session, owner, q0.id, gone.id)
    exp_service.link(db_session, owner, q2.id, on_deleted_q.id)
    exp_service.soft_delete_experience(db_session, gone)
    q2.deleted_at = datetime.now(UTC)
    db_session.flush()

    got = linked_experiences_for_resume(db_session, owner, r.id)
    assert [x["id"] for x in got] == [e1.id, e2.id], "문항 순서(q0→q1), 중복·삭제 제외"
    assert got[0]["title"] == f"경험1 {PII}", "원문으로 복원"
    assert linked_experiences_for_resume(db_session, other, r.id) == [], "남의 자소서"
    assert linked_experiences_for_resume(db_session, owner, uuid.uuid4()) == [], "없는 자소서"
    r.deleted_at = datetime.now(UTC)
    db_session.flush()
    assert linked_experiences_for_resume(db_session, owner, r.id) == [], "삭제된 자소서"

