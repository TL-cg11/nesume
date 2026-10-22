"""B3 감사 로그 무결성 제약·90일 보관 정리."""
import hashlib
import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.db import engine
from app.features.audit import retention
from app.models import AuditLog
from app.models._common import GRADES

SHA = hashlib.sha256(b"query").hexdigest()


def _log(**kw):
    base = dict(request_id=uuid.uuid4(), session_id="s-1", user_id="u-1", role="user",
                feature="rewrite", decision="allow", is_test=False)
    base.update(kw)
    return AuditLog(**base)


def _constraint_def(name: str) -> str:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"), {"n": name}
        ).scalar_one()


def test_doc_grades_constraint_matches_grade_enum():
    assert set(re.findall(r"'(\w+)'", _constraint_def("ck_audit_logs_doc_grades_known"))) == set(GRADES)


# --- 정상 저장 --------------------------------------------------------------

@pytest.mark.parametrize(
    "kw",
    [
        pytest.param({}, id="minimal"),
        pytest.param({"doc_ids": ["d1", "d2"], "doc_grades": ["personal", "public"]}, id="doc-grades"),
        pytest.param({"session_id": "test-run-1", "is_test": True}, id="test-traffic"),
        pytest.param({"query_hash": SHA}, id="sha256"),
        pytest.param({"query_hash": None}, id="no-hash"),
    ],
)
def test_valid_rows_saved(db_session, kw):
    db_session.add(_log(**kw))
    db_session.flush()


# --- 제약 위반 ---------------------------------------------------------------

@pytest.mark.parametrize(
    "kw",
    [
        pytest.param({"doc_grades": ["personal", "secret"]}, id="unknown-grade"),
        pytest.param({"session_id": "test-run-1", "is_test": False}, id="test-prefix-without-flag"),
        pytest.param({"session_id": "s-1", "is_test": True}, id="flag-without-test-prefix"),
        pytest.param({"query_hash": "김철수 010-1234-5678 지원 동기"}, id="raw-query-in-hash"),
        pytest.param({"query_hash": SHA.upper()}, id="uppercase-hash"),
        pytest.param({"query_hash": SHA[:63]}, id="short-hash"),
    ],
)
def test_invalid_rows_rejected(db_session, kw):
    db_session.add(_log(**kw))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_doc_ids_and_grades_length_enforced(db_session):
    # A8이 1:1로 기록함을 확인한 뒤 B11(마이그레이션 0009)에서 추가(part2_guide 4.29)
    db_session.add(_log(doc_ids=["d1", "d2"], doc_grades=["personal"]))
    with pytest.raises(IntegrityError):
        db_session.flush()


# --- 90일 보관 정리 ---------------------------------------------------------

def _seed_ages(db, days_list, marker):
    now = datetime.now(UTC)
    for d in days_list:
        db.add(_log(session_id=marker, feature=f"{d}d", timestamp=now - timedelta(days=d)))
    db.flush()
    return now


def _remaining(db, marker):
    return sorted(db.scalars(select(AuditLog.feature).where(AuditLog.session_id == marker)).all())


def test_retention_deletes_only_rows_older_than_90_days(db_session):
    marker = f"s-{uuid.uuid4().hex[:8]}"
    now = _seed_ages(db_session, [91, 120, 89, 1], marker)
    assert retention.cleanup(db_session, now=now) == 2
    assert _remaining(db_session, marker) == ["1d", "89d"]


def test_retention_respects_batch_and_deletes_oldest_first(db_session):
    marker = f"s-{uuid.uuid4().hex[:8]}"
    now = _seed_ages(db_session, [95, 200, 150, 10], marker)
    assert retention.cleanup(db_session, now=now, batch=2) == 2
    assert _remaining(db_session, marker) == ["10d", "95d"]
    assert retention.cleanup(db_session, now=now, batch=2) == 1
    assert retention.cleanup(db_session, now=now, batch=2) == 0


def test_retention_defaults():
    assert retention.RETENTION == timedelta(days=90)
    assert retention.CLEANUP_BATCH == 5000


def test_retention_includes_test_traffic(db_session):
    # spec 10.2 보관 90일은 전체 로그 기준
    now = datetime.now(UTC)
    db_session.add(_log(session_id="test-old", is_test=True, timestamp=now - timedelta(days=100)))
    db_session.flush()
    retention.cleanup(db_session, now=now)
    assert db_session.scalar(select(func.count()).where(AuditLog.session_id == "test-old")) == 0
