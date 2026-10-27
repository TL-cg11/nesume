"""B11 감사 로그 기록 함수(AuditSink) · 운영자 조회 API · 수정·삭제 방지."""
import asyncio
import hashlib
import importlib.util
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import IntegrityError

from app.auth import CurrentUser, Role, get_current_user, mfa
from app.config import get_settings
from app.core.errors import register_exception_handlers
from app.db import SessionLocal
from app.features.audit import retention
from app.features.audit.router import router as audit_router
from app.features.audit.sink import AuditRecordInvalid, DbAuditSink
from app.models import AuditLog, User

# main.py(D 소유) 등록은 D팀에 요청. 테스트는 라우터를 테스트 앱에 직접 붙여 검증한다.
app = FastAPI()
register_exception_handlers(app)
app.include_router(audit_router)


def _fields(**kw):
    """A8 _write_audit + Verdict.to_audit_fields()와 같은 키."""
    base = dict(
        request_id=uuid.uuid4(), session_id="sess-1", user_id=f"u-{uuid.uuid4().hex[:8]}", role="user",
        feature="rewrite", query_masked="연락처 ***-****-****", query_hash=hashlib.sha256(b"q").hexdigest(),
        doc_ids=["d1", "d2"], doc_grades=["personal", "public"], is_test=False, latency_ms=120,
        decision="allow", decision_stage="classifier", query_type="normal", flags=[], rule_id=None,
        canary_hit=False,
    )
    base.update(kw)
    return base


def write(**fields):
    asyncio.run(DbAuditSink().write(**fields))


def _get(request_id):
    with SessionLocal() as db:
        return db.get(AuditLog, request_id)


# --- 기록 함수 ---------------------------------------------------------------

def test_write_stores_all_fields():
    f = _fields(flags=["R-EXFIL-003"], rule_id="R-EXFIL-003", decision="block", query_type="exfiltration")
    write(**f)
    row = _get(f["request_id"])
    for k, v in f.items():
        assert getattr(row, k) == v, k
    assert row.grade == "sensitive" and row.timestamp is not None


@pytest.mark.parametrize(
    "kw",
    [
        pytest.param({"unexpected": "x"}, id="unknown-key"),
        pytest.param({"query": "원문 질의"}, id="raw-query-key"),
        pytest.param({"decision": "flag"}, id="decision-flag"),
        pytest.param({"role": "admin"}, id="unknown-role"),
        pytest.param({"query_hash": "김철수 010-1234-5678"}, id="raw-in-hash"),
        pytest.param({"doc_grades": ["personal", "secret"]}, id="unknown-grade"),
        pytest.param({"doc_ids": ["d1"]}, id="length-mismatch"),
        pytest.param({"is_test": True}, id="test-flag-without-prefix"),
        pytest.param({"session_id": "test-run-1"}, id="test-prefix-without-flag"),
    ],
)
def test_write_rejects_invalid_and_saves_nothing(kw):
    f = _fields(**kw)
    with pytest.raises(AuditRecordInvalid):
        write(**f)
    assert _get(f["request_id"]) is None


def test_error_message_does_not_echo_values():
    with pytest.raises(AuditRecordInvalid) as e:
        write(**_fields(query_hash="김철수 010-1234-5678"))
    assert "김철수" not in str(e.value) and "010" not in str(e.value)


def test_test_traffic_accepted_with_prefix():
    f = _fields(session_id="test-run-1", is_test=True)
    write(**f)
    assert _get(f["request_id"]).is_test is True


# --- DB 제약·변조 방지 -------------------------------------------------------

def test_length_mismatch_rejected_by_db(db_session):
    db_session.add(AuditLog(**{k: v for k, v in _fields(doc_ids=["d1"]).items()}))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.fixture
def stored(db_session):
    f = _fields()
    db_session.add(AuditLog(**f))
    db_session.flush()
    return f


@pytest.mark.parametrize("values", [
    pytest.param({"decision": "block"}, id="decision"),
    pytest.param({"query_masked": "변조"}, id="query_masked"),
    pytest.param({"is_test": True, "session_id": "test-x"}, id="is_test"),
])
def test_update_other_columns_rejected(db_session, stored, values):
    with pytest.raises(IntegrityError, match="immutable"):
        db_session.execute(update(AuditLog).where(AuditLog.request_id == stored["request_id"]).values(**values))


def test_user_id_change_to_non_anon_value_rejected(db_session, stored):
    with pytest.raises(IntegrityError, match="anonymization"):
        db_session.execute(update(AuditLog).where(AuditLog.request_id == stored["request_id"]).values(user_id="someone"))


def test_user_id_anonymization_allowed(db_session, stored):
    # B20: 계정 삭제 시 users.anon_id 로 치환
    anon = f"anon-{uuid.uuid4().hex}"
    db_session.add(User(id=stored["user_id"], anon_id=anon))
    db_session.flush()
    db_session.execute(update(AuditLog).where(AuditLog.request_id == stored["request_id"]).values(user_id=anon))
    assert db_session.get(AuditLog, stored["request_id"]).user_id == anon


def test_delete_within_retention_rejected(db_session, stored):
    with pytest.raises(IntegrityError, match="retention"):
        db_session.execute(delete(AuditLog).where(AuditLog.request_id == stored["request_id"]))


def test_delete_after_retention_allowed(db_session):
    f = _fields()
    db_session.add(AuditLog(**f, timestamp=datetime.now(UTC) - timedelta(days=91)))
    db_session.flush()
    db_session.execute(delete(AuditLog).where(AuditLog.request_id == f["request_id"]))
    assert db_session.get(AuditLog, f["request_id"]) is None


def test_truncate_rejected(db_session):
    with pytest.raises(IntegrityError, match="truncated"):
        db_session.execute(text("TRUNCATE audit_logs"))


def test_retention_batch_still_works_with_guard(db_session):
    old = _fields()
    db_session.add(AuditLog(**old, timestamp=datetime.now(UTC) - timedelta(days=100)))
    db_session.flush()
    retention.cleanup(db_session)
    assert db_session.get(AuditLog, old["request_id"]) is None


def test_trigger_retention_matches_cleanup_constant():
    path = next(Path("/srv/migrations/versions").glob("*_0009_*.py"))
    spec = importlib.util.spec_from_file_location("m0009", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.RETENTION_INTERVAL == f"{retention.RETENTION.days} days"


# --- 운영자 조회 API ---------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _client(role=Role.OPERATOR, *, mfa_required=False, auth_time=None):
    """기본은 MFA 검사를 끈 상태(로컬과 같음). MFA 동작은 test_operator_mfa_*에서 따로 본다."""
    now = int(time.time())
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        sub=f"op-{uuid.uuid4()}", role=role, auth_time=now if auth_time is None else auth_time)
    app.dependency_overrides[get_settings] = lambda: get_settings().model_copy(
        update={"operator_mfa_required": mfa_required})
    return TestClient(app)


@pytest.fixture(scope="module")
def seeded():
    """조회 테스트용 로그. 다른 테스트와 겹치지 않도록 고유 feature로 구분."""
    tag = f"feat-{uuid.uuid4().hex[:6]}"
    now = datetime.now(UTC)
    rows = [
        _fields(feature=tag, user_id="alice", decision="allow", query_type="normal"),
        _fields(feature=tag, user_id="alice", decision="block", query_type="exfiltration", role="mentor"),
        _fields(feature=tag, user_id="bob", decision="mask", query_type="sensitive",
                session_id="test-r1", is_test=True),
    ]
    with SessionLocal() as db:
        for i, r in enumerate(rows):
            db.add(AuditLog(**r, timestamp=now - timedelta(minutes=i)))
        db.commit()
    return tag, rows, now


@pytest.mark.parametrize("role", [Role.USER, Role.MENTOR, Role.SYSTEM])
def test_non_operator_forbidden(role):
    assert _client(role).get("/audit-logs").status_code == 403
    assert _client(role, mfa_required=True).get("/audit-logs").status_code == 403


def test_operator_mfa_required(monkeypatch):
    # 운영자라도 TOTP 미등록이면 403 mfa_required(D7 require_operator_mfa)
    monkeypatch.setattr(mfa, "totp_enrolled", lambda sub: False)
    res = _client(mfa_required=True).get("/audit-logs")
    assert res.status_code == 403 and res.json()["code"] == "mfa_required"


def test_operator_mfa_session_expired(monkeypatch):
    # TOTP 등록했어도 로그인한 지 오래되면(MFA 세션 만료) 다시 로그인
    monkeypatch.setattr(mfa, "totp_enrolled", lambda sub: True)
    stale = int(time.time()) - (get_settings().mfa_session_minutes + 1) * 60
    res = _client(mfa_required=True, auth_time=stale).get("/audit-logs")
    assert res.status_code == 403 and res.json()["code"] == "mfa_session_expired"


def test_operator_with_mfa_session_ok(monkeypatch):
    monkeypatch.setattr(mfa, "totp_enrolled", lambda sub: True)
    assert _client(mfa_required=True).get("/audit-logs").status_code == 200


def test_requires_authentication():
    assert TestClient(app).get("/audit-logs").status_code == 401


def test_operator_lists_newest_first(seeded):
    tag, rows, _ = seeded
    got = _client().get("/audit-logs", params={"feature": tag}).json()
    assert [g["request_id"] for g in got] == [str(r["request_id"]) for r in rows]


@pytest.mark.parametrize("params,expected", [
    ({"user_id": "alice"}, 2),
    ({"role": "mentor"}, 1),
    ({"query_type": "sensitive"}, 1),
    ({"decision": "block"}, 1),
    ({"is_test": "true"}, 1),
    ({"is_test": "false"}, 2),
])
def test_filters(seeded, params, expected):
    tag, _, _ = seeded
    assert len(_client().get("/audit-logs", params={"feature": tag, **params}).json()) == expected


def test_period_filter(seeded):
    tag, _, now = seeded
    got = _client().get("/audit-logs", params={
        "feature": tag, "from": (now - timedelta(seconds=90)).isoformat(), "to": now.isoformat(),
    }).json()
    assert len(got) == 1  # now-1분 행만 [from, to) 안에 든다


def test_pagination_limits(seeded):
    tag, _, _ = seeded
    c = _client()
    assert len(c.get("/audit-logs", params={"feature": tag, "limit": 2}).json()) == 2
    assert len(c.get("/audit-logs", params={"feature": tag, "limit": 2, "offset": 2}).json()) == 1
    assert c.get("/audit-logs", params={"limit": 501}).status_code == 422
