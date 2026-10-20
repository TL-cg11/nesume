"""B2 문서 등급 컬럼 검증."""
import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.db import engine
from app.models import (
    Application,
    AuditLog,
    Experience,
    PromptTemplate,
    Question,
    Resume,
    User,
    Version,
)
from app.models._common import GRADES, Grade

ALEMBIC = Config("/srv/alembic.ini")

# spec 6.4 기능별 등급
EXPECTED_DEFAULT = {
    "resumes": Grade.PERSONAL,
    "questions": Grade.PERSONAL,
    "versions": Grade.PERSONAL,
    "experiences": Grade.PERSONAL,
    "applications": Grade.PERSONAL,
    "templates": Grade.INTERNAL,
    "audit_logs": Grade.SENSITIVE,
}


def _seed(session):
    """테이블별 최소 행을 하나씩 만들고 {테이블: 객체}를 반환한다."""
    u = User(id=str(uuid.uuid4()))
    session.add(u)
    session.flush()  # users ↔ 문서 간 relationship이 없어 INSERT 순서를 명시적으로 보장
    r = Resume(owner_id=u.id, title="t")
    session.add(r)
    session.flush()
    q = Question(resume_id=r.id, owner_id=u.id, title="q")
    session.add(q)
    session.flush()
    rows = {
        "resumes": r,
        "questions": q,
        "versions": Version(question_id=q.id, owner_id=u.id, version_no=1, body="b",
                            char_count=1, source="manual"),
        "experiences": Experience(owner_id=u.id, title="e", type="project"),
        "applications": Application(owner_id=u.id, status="applied"),
        "templates": PromptTemplate(name=f"t-{uuid.uuid4().hex[:6]}", purpose="rewrite", body="b",
                                    version=1, created_by="op"),
        "audit_logs": AuditLog(request_id=uuid.uuid4(), session_id="s", user_id=u.id, role="user",
                               feature="rewrite", decision="allow"),
    }
    session.add_all(rows.values())
    session.flush()
    return rows


def test_grade_enum_matches_spec():
    assert GRADES == ("public", "internal", "personal", "sensitive", "confidential")


@pytest.mark.parametrize("table", sorted(EXPECTED_DEFAULT))
def test_db_check_constraint_allows_exactly_grade_enum(table):
    # alembic check는 CHECK 제약을 비교하지 않으므로 DB 정의를 직접 확인한다
    with engine.connect() as conn:
        definition = conn.execute(
            text("""
                SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                WHERE t.relname = :t AND c.conname = :n
            """),
            {"t": table, "n": f"ck_{table}_grade"},
        ).scalar_one()
    assert set(re.findall(r"'(\w+)'", definition)) == set(GRADES)


def test_defaults_follow_spec_6_4(db_session):
    rows = _seed(db_session)
    for table, obj in rows.items():
        db_session.refresh(obj)
        assert obj.grade == EXPECTED_DEFAULT[table], table


@pytest.mark.parametrize("table", sorted(EXPECTED_DEFAULT))
def test_server_default_applies_to_raw_insert(db_session, table):
    # ORM을 거치지 않는 INSERT(배치·타 팀 코드)에도 기본 등급이 붙는다
    rows = _seed(db_session)
    pk = "request_id" if table == "audit_logs" else "id"
    grade = db_session.execute(
        text(f"SELECT grade FROM {table} WHERE {pk} = :id"), {"id": getattr(rows[table], pk)}
    ).scalar_one()
    assert grade == EXPECTED_DEFAULT[table]


@pytest.mark.parametrize("table", sorted(EXPECTED_DEFAULT))
def test_unknown_grade_rejected(db_session, table):
    rows = _seed(db_session)
    if table == "versions":
        # versions는 UPDATE 자체가 트리거로 막히므로 INSERT로 확인한다
        stmt = text(
            "INSERT INTO versions (question_id, owner_id, version_no, body, char_count, source, grade)"
            " VALUES (:q, :o, 2, 'b', 1, 'manual', 'secret')"
        )
        params = {"q": rows["questions"].id, "o": rows["questions"].owner_id}
    else:
        pk = "request_id" if table == "audit_logs" else "id"
        stmt = text(f"UPDATE {table} SET grade = 'secret' WHERE {pk} = :id")
        params = {"id": getattr(rows[table], pk)}
    with pytest.raises(IntegrityError):
        db_session.execute(stmt, params)


def test_active_share_lookup_index_exists():
    idx = {i["name"]: i for i in inspect(engine).get_indexes("shares")}
    assert idx["ix_shares_active_lookup"]["column_names"] == ["shared_with", "resume_id", "expires_at"]


def test_active_share_lookup_uses_partial_index(db_session):
    owner, mentor = User(id=str(uuid.uuid4())), User(id=str(uuid.uuid4()))
    db_session.add_all([owner, mentor])
    db_session.flush()
    r = Resume(owner_id=owner.id, title="t")
    db_session.add(r)
    db_session.flush()
    db_session.execute(text("SET LOCAL enable_seqscan = off"))
    plan = "\n".join(
        db_session.execute(
            text("""
                EXPLAIN SELECT 1 FROM shares
                WHERE shared_with = :m AND resume_id = :r AND revoked_at IS NULL AND expires_at > :now
            """),
            {"m": mentor.id, "r": r.id, "now": datetime.now(UTC) + timedelta(days=1)},
        ).scalars()
    )
    assert "ix_shares_active_lookup" in plan


def test_downgrade_to_b1_removes_grade_then_upgrade():
    command.downgrade(ALEMBIC, "0002")
    try:
        assert "grade" not in {c["name"] for c in inspect(engine).get_columns("resumes")}
    finally:
        command.upgrade(ALEMBIC, "head")
    assert "grade" in {c["name"] for c in inspect(engine).get_columns("resumes")}


def test_resume_shared_with_defaults_to_empty_array(db_session):
    rows = _seed(db_session)
    db_session.refresh(rows["resumes"])
    assert rows["resumes"].shared_with == []


def test_resume_shared_with_holds_per_mentor_expiry(db_session):
    rows = _seed(db_session)
    r = rows["resumes"]
    entries = [
        {"user_id": "mentor-a", "expires_at": "2026-10-22T00:00:00+00:00"},
        {"user_id": "mentor-b", "expires_at": "2026-11-14T00:00:00+00:00"},
    ]
    r.shared_with = entries
    db_session.flush()
    db_session.refresh(r)
    assert r.shared_with == entries


def test_resume_shared_with_must_be_array(db_session):
    rows = _seed(db_session)
    with pytest.raises(IntegrityError):
        db_session.execute(
            text("""UPDATE resumes SET shared_with = '{"user_id": "x"}'::jsonb WHERE id = :id"""),
            {"id": rows["resumes"].id},
        )
