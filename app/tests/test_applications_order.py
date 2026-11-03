"""C15 칸반 순서·불합격 삭제 테스트 (DB 필요, conftest `db_session`)."""
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.features.applications import service
from app.models.application import APPLICATION_STATUSES, Application
from app.models.user import User


def _user(session) -> str:
    uid = str(uuid.uuid4())
    session.add(User(id=uid))
    session.flush()
    return uid


def _app(session, owner, status="applied"):
    a = service.create_application(session, owner_id=owner, status=status)
    session.flush()
    return a


def _column(session, owner, status):
    return [
        a.id
        for a, _ in service.list_applications(session, owner_id=owner)
        if a.status == status
    ]


def test_rejected_status_removed():
    assert "rejected" not in APPLICATION_STATUSES
    assert APPLICATION_STATUSES == ("applied", "document_passed", "interview", "final")


def test_rejected_rejected_by_service_and_db(db_session):
    owner = _user(db_session)
    with pytest.raises(ValueError):
        service.create_application(db_session, owner_id=owner, status="rejected")
    # DB CHECK 제약도 막는다(마이그레이션 0019)
    sql = "INSERT INTO applications (id, owner_id, status, grade) VALUES (:i, :o, 'rejected', 'personal')"
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.execute(text(sql), {"i": uuid.uuid4(), "o": owner})


def test_new_card_goes_to_bottom(db_session):
    owner = _user(db_session)
    a, b, c = (_app(db_session, owner) for _ in range(3))
    assert [a.position, b.position, c.position] == [0, 1, 2]
    assert _column(db_session, owner, "applied") == [a.id, b.id, c.id]


def test_reorder_within_column(db_session):
    owner = _user(db_session)
    a, b, c = (_app(db_session, owner) for _ in range(3))
    service.reorder(db_session, owner_id=owner, status="applied", ids=[c.id, a.id, b.id])
    db_session.flush()
    assert _column(db_session, owner, "applied") == [c.id, a.id, b.id]


def test_reorder_moves_card_from_other_column(db_session):
    """다른 열 카드를 넣으면 상태도 바뀐다(드래그 이동 = 상태 + 자리)."""
    owner = _user(db_session)
    a = _app(db_session, owner, "applied")
    x, y = _app(db_session, owner, "interview"), _app(db_session, owner, "interview")
    service.reorder(db_session, owner_id=owner, status="interview", ids=[x.id, a.id, y.id])
    db_session.flush()
    assert a.status == "interview"
    assert _column(db_session, owner, "interview") == [x.id, a.id, y.id]
    assert _column(db_session, owner, "applied") == []


def test_reorder_keeps_cards_missing_from_request(db_session):
    """요청에 빠진 같은 열 카드(동시 수정)는 버리지 않고 뒤에 순서대로 붙인다."""
    owner = _user(db_session)
    a, b, c = (_app(db_session, owner) for _ in range(3))
    service.reorder(db_session, owner_id=owner, status="applied", ids=[c.id])
    db_session.flush()
    assert _column(db_session, owner, "applied") == [c.id, a.id, b.id]


def test_reorder_rejects_others_records_entirely(db_session):
    """남의 기록·없는 id가 하나라도 섞이면 전체 거부 — 내 카드 순서도 안 바뀐다."""
    me, other = _user(db_session), _user(db_session)
    a, b = _app(db_session, me), _app(db_session, me)
    theirs = _app(db_session, other)
    for bad in (theirs.id, uuid.uuid4()):
        with pytest.raises(service.ApplicationNotFound):
            service.reorder(db_session, owner_id=me, status="applied", ids=[b.id, bad, a.id])
    db_session.flush()
    assert _column(db_session, me, "applied") == [a.id, b.id]
    assert theirs.status == "applied" and theirs.owner_id == other


def test_reorder_unknown_status(db_session):
    owner = _user(db_session)
    a = _app(db_session, owner)
    with pytest.raises(ValueError):
        service.reorder(db_session, owner_id=owner, status="rejected", ids=[a.id])


def test_stats_have_four_statuses(db_session):
    owner = _user(db_session)
    _app(db_session, owner, "final")
    counts = service.aggregate_by_status(db_session, owner_id=owner)
    assert set(counts) == set(APPLICATION_STATUSES) and counts["final"] == 1
    assert db_session.execute(select(Application).where(Application.owner_id == owner)).scalars().one()
