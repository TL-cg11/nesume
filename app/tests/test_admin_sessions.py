"""D16 운영자 세션 차단 API — 목록·수동 차단·해제, 권한(운영자 MFA), 감사 로그 줄. Postgres 테스트 DB 사용."""
import logging
import time
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.auth.cognito import TokenVerifier, get_token_verifier
from app.core import session_block
from app.db import get_db
from app.main import app
from app.models import AuditLog

ISSUER = "https://issuer.test/pool"
CLIENT_ID = "test-client"


@pytest.fixture(scope="module")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _token(key, sub: str, groups: list[str]) -> str:
    now = int(time.time())
    claims = {
        "sub": sub, "iss": ISSUER, "client_id": CLIENT_ID, "token_use": "access",
        "iat": now, "exp": now + 300, "cognito:groups": groups,
    }
    return jwt.encode(claims, key, algorithm="RS256")


@pytest.fixture
def setup(rsa_key, db_session):
    verifier = TokenVerifier(ISSUER, CLIENT_ID, key_resolver=lambda _t: rsa_key.public_key())
    app.dependency_overrides[get_token_verifier] = lambda: verifier
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)
    operator_sub = str(uuid.uuid4())
    headers = {"Authorization": f"Bearer {_token(rsa_key, operator_sub, ['operator', 'test'])}"}
    user_headers = {"Authorization": f"Bearer {_token(rsa_key, str(uuid.uuid4()), [])}"}
    try:
        yield client, headers, user_headers, operator_sub, db_session
    finally:
        app.dependency_overrides.clear()


def test_requires_operator(setup):
    client, _, user_headers, _, _ = setup
    assert client.get("/admin/sessions/blocked", headers=user_headers).status_code == 403
    assert client.get("/admin/sessions/blocked").status_code == 401
    assert client.post("/admin/sessions/s1/block", json={}, headers=user_headers).status_code == 403


def test_block_list_release_flow(setup, caplog):
    client, headers, _, operator_sub, db = setup
    sid = f"sess-{uuid.uuid4().hex[:8]}"
    # 감사 로그에서 세션의 사용자를 찾는다
    db.add(AuditLog(
        request_id=uuid.uuid4(), session_id=sid, user_id="u-victim", role="user",
        timestamp=datetime.now(UTC), feature="rewrite", decision="block", query_type="exfiltration",
        flags=["INJ_DIRECT"], is_test=False, latency_ms=10,
    ))
    db.flush()

    with caplog.at_level(logging.INFO, logger="nesume.audit.admin"):
        r = client.post(f"/admin/sessions/{sid}/block", json={"note": "수동", "minutes": 30}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["session_id"] == sid and body["user_id"] == "u-victim" and body["reason"] == "operator"
    assert body["blocked_by"] == operator_sub and body["active"] is True and body["expires_at"] is not None
    assert any(rec.getMessage() == "session_blocked" for rec in caplog.records)

    listed = client.get("/admin/sessions/blocked", headers=headers).json()
    assert [row["session_id"] for row in listed if row["session_id"] == sid] == [sid]
    assert session_block.active_block(db, sid) is not None

    # 같은 세션 재차단 → 갱신(200), 새 행 아님
    r = client.post(f"/admin/sessions/{sid}/block", json={}, headers=headers)
    assert r.status_code == 200 and r.json()["expires_at"] is None  # 만료 없는 차단으로 올라감

    with caplog.at_level(logging.INFO, logger="nesume.audit.admin"):
        r = client.delete(f"/admin/sessions/{sid}/block", headers=headers)
    assert r.status_code == 200 and r.json()["active"] is False and r.json()["released_by"] == operator_sub
    assert any(rec.getMessage() == "session_released" for rec in caplog.records)
    assert session_block.active_block(db, sid) is None
    # 유효한 목록에서 빠지고, 이력(active=false)에는 남는다
    active_ids = [row["session_id"] for row in client.get("/admin/sessions/blocked", headers=headers).json()]
    assert sid not in active_ids
    history = client.get("/admin/sessions/blocked?active=false", headers=headers).json()
    assert any(row["session_id"] == sid and row["active"] is False for row in history)

    # 다시 해제 → 404
    assert client.delete(f"/admin/sessions/{sid}/block", headers=headers).status_code == 404


def test_unknown_session_blocks_with_unknown_user(setup):
    client, headers, _, _, _ = setup
    sid = f"sess-{uuid.uuid4().hex[:8]}"
    r = client.post(f"/admin/sessions/{sid}/block", json={}, headers=headers)
    assert r.status_code == 200 and r.json()["user_id"] == "unknown"


def test_validation(setup):
    client, headers, _, _, _ = setup
    assert client.post("/admin/sessions/x/block", json={"minutes": 0}, headers=headers).status_code == 422
    too_long = {"note": "n" * 301}
    assert client.post("/admin/sessions/x/block", json=too_long, headers=headers).status_code == 422
    assert client.post(f"/admin/sessions/{'s' * 129}/block", json={}, headers=headers).status_code == 422


def test_auto_blocked_session_is_rejected_on_llm_path(setup):
    """래퍼(core/session_block)가 넣은 차단을 목록 API 로 보고 해제할 수 있다 — 자동·수동이 같은 표."""
    client, headers, _, _, db = setup
    sid = f"sess-{uuid.uuid4().hex[:8]}"
    session_block.block(
        db, sid, user_id="u-1", reason="exfil_threshold", rule_id="INJ_DIRECT",
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    rows = client.get("/admin/sessions/blocked", headers=headers).json()
    mine = next(r for r in rows if r["session_id"] == sid)
    assert mine["reason"] == "exfil_threshold" and mine["blocked_by"] == "system"
    assert mine["rule_id"] == "INJ_DIRECT"
    assert client.delete(f"/admin/sessions/{sid}/block", headers=headers).status_code == 200
