"""D14·D15 운영자 대시보드: 트래픽 집계(core/metrics)와 감사 로그 집계 API."""
import json
import logging
import time
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.auth.cognito import TokenVerifier, get_token_verifier
from app.core.logging import JsonFormatter
from app.core.metrics import TrafficStats, normalize_route
from app.db import get_db
from app.main import app
from app.models import AuditLog

ISSUER = "https://issuer.test/pool"
CLIENT_ID = "test-client"


# ---------- core/metrics ----------


def test_normalize_route_collapses_ids():
    rid = "3f2a7c1e-9b3d-4f1a-8c2e-1a2b3c4d5e6f"
    assert normalize_route(f"/resumes/{rid}/versions/12") == "/resumes/{id}/versions/{id}"
    assert normalize_route("/admin/users/abcdef0123456789abcdef01/role") == "/admin/users/{id}/role"
    assert normalize_route("/health") == "/health"


def test_traffic_snapshot_counts_and_percentiles():
    now = [1_700_000_000.0]
    stats = TrafficStats(clock=lambda: now[0])
    for ms in (10, 20, 30, 40, 2000):
        stats.record("GET", "/resumes", 200, ms, role="user")
    stats.record("POST", "/resumes", 500, 80, role="user")
    stats.record("GET", "/resumes/abc", 404, 5, role="mentor")  # abc 는 ID 아님(짧음)
    stats.record("GET", "/health", 200, 1)  # 프로브 제외
    stats.record("POST", "/writing/rewrite", 200, 300, role="user", is_test=True)  # 평가 트래픽 제외

    snap = stats.snapshot(minutes=60)
    t = snap["totals"]
    assert t["requests"] == 7
    assert t["errors_5xx"] == 1 and t["client_4xx"] == 1
    assert t["test_requests"] == 1 and t["probe_requests"] == 1
    assert snap["status"] == {"2xx": 5, "3xx": 0, "4xx": 1, "5xx": 1}
    assert snap["by_role"] == {"user": 6, "mentor": 1}
    assert t["latency_ms"]["p50"] is not None and t["latency_ms"]["p50"] <= 50
    assert t["latency_ms"]["p99"] > 1000
    assert snap["routes"][0]["route"] == "/resumes" and snap["routes"][0]["requests"] == 5
    assert len(snap["series"]) == 60 and snap["series"][-1]["requests"] == 7


def test_traffic_evicts_old_minutes():
    now = [1_700_000_000.0]
    stats = TrafficStats(window_minutes=10, clock=lambda: now[0])
    stats.record("GET", "/a", 200, 1)
    now[0] += 11 * 60
    stats.record("GET", "/a", 200, 1)
    assert stats.snapshot(minutes=10)["totals"]["requests"] == 1


def test_json_log_has_log_type():
    fmt = JsonFormatter()
    app_line = json.loads(
        fmt.format(logging.LogRecord("nesume.access", logging.INFO, __file__, 1, "x", None, None))
    )
    audit_line = json.loads(
        fmt.format(logging.LogRecord("nesume.audit.admin", logging.INFO, __file__, 1, "y", None, None))
    )
    assert app_line["log_type"] == "app"
    assert audit_line["log_type"] == "audit"


# ---------- /admin/dashboard ----------


@pytest.fixture(scope="module")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _token(key, sub: str, groups: list[str]) -> str:
    now = int(time.time())
    claims = {
        "sub": sub,
        "iss": ISSUER,
        "client_id": CLIENT_ID,
        "token_use": "access",
        "iat": now,
        "exp": now + 300,
        "cognito:groups": groups,
    }
    return jwt.encode(claims, key, algorithm="RS256")


def _log(user_id: str, decision: str, *, minutes_ago: int = 5, flags=(), is_test=False, **extra) -> AuditLog:
    return AuditLog(
        request_id=uuid.uuid4(),
        session_id=("test-" if is_test else "sess-") + uuid.uuid4().hex[:8],
        user_id=user_id,
        role=extra.pop("role", "user"),
        timestamp=datetime.now(UTC) - timedelta(minutes=minutes_ago),
        feature=extra.pop("feature", "rewrite"),
        query_type=extra.pop("query_type", "normal"),
        flags=list(flags),
        decision=decision,
        is_test=is_test,
        latency_ms=extra.pop("latency_ms", 100),
        **extra,
    )


@pytest.fixture
def setup(rsa_key, db_session):
    verifier = TokenVerifier(ISSUER, CLIENT_ID, key_resolver=lambda _t: rsa_key.public_key())
    app.dependency_overrides[get_token_verifier] = lambda: verifier
    app.dependency_overrides[get_db] = lambda: db_session
    attacker, normal = f"u-{uuid.uuid4().hex[:8]}", f"u-{uuid.uuid4().hex[:8]}"
    db_session.add_all(
        [
            _log(normal, "allow"),
            _log(normal, "allow", feature="interview"),
            _log(
                attacker, "block", flags=["injection"], query_type="exfiltration", decision_stage="classifier"
            ),
            _log(attacker, "mask", flags=["pii"], query_type="sensitive", decision_stage="output_guard"),
            _log(attacker, "allow", canary_hit=True),
            _log(normal, "block", flags=["x"], is_test=True),  # 평가 러너: 기본 제외
            _log(normal, "block", flags=["x"], minutes_ago=3 * 24 * 60),  # 창 밖(직전 24시간에도 없음)
        ]
    )
    db_session.flush()
    try:
        yield {
            "client": TestClient(app),
            "operator": _token(rsa_key, str(uuid.uuid4()), ["operator", "test"]),
            "user": _token(rsa_key, str(uuid.uuid4()), ["test"]),
            "attacker": attacker,
            "normal": normal,
        }
    finally:
        app.dependency_overrides.clear()


def _get(ctx, path, token):
    return ctx["client"].get(path, headers={"Authorization": f"Bearer {token}"})


def test_summary_excludes_test_traffic_by_default(setup):
    r = _get(setup, "/admin/dashboard/summary?hours=24", setup["operator"])
    assert r.status_code == 200, r.text
    body = r.json()
    t = body["totals"]
    assert (t["requests"], t["allow"], t["mask"], t["block"]) == (5, 3, 1, 1)
    assert t["flagged"] == 2 and t["canary_hits"] == 1
    assert t["block_rate"] == 0.2 and t["flag_rate"] == 0.4
    assert {c["key"]: c["requests"] for c in body["by_decision"]} == {"allow": 3, "block": 1, "mask": 1}
    assert {c["key"] for c in body["by_feature"]} == {"rewrite", "interview"}
    assert body["by_stage"][0]["key"] in ("classifier", "output_guard", "(없음)")
    assert body["top_users"][0]["user_id"] == setup["attacker"]
    assert body["top_users"][0]["flag_rate"] == round(2 / 3, 4)
    assert all(u["user_id"] != setup["normal"] for u in body["top_users"])  # flag 없음 → 목록에 없음
    assert len(body["recent_events"]) == 3  # block + mask + canary
    assert "query_masked" not in body["recent_events"][0]
    assert sum(p["allow"] + p["mask"] + p["block"] for p in body["series"]) == 5
    assert len(body["series"]) == 24 and body["step_minutes"] == 60
    assert body["previous"] == {"requests": 0, "block": 0, "flagged": 0}


def test_summary_include_test(setup):
    body = _get(setup, "/admin/dashboard/summary?hours=24&include_test=true", setup["operator"]).json()
    assert body["totals"]["requests"] == 6 and body["totals"]["block"] == 2


def test_summary_short_window_has_fine_steps(setup):
    body = _get(setup, "/admin/dashboard/summary?hours=1", setup["operator"]).json()
    assert body["step_minutes"] == 5 and len(body["series"]) == 12


def test_summary_rejects_bad_hours(setup):
    assert _get(setup, "/admin/dashboard/summary?hours=0", setup["operator"]).status_code == 422
    assert _get(setup, "/admin/dashboard/summary?hours=999", setup["operator"]).status_code == 422


def test_dashboard_is_operator_only(setup):
    assert _get(setup, "/admin/dashboard/summary", setup["user"]).status_code == 403
    assert _get(setup, "/admin/dashboard/traffic", setup["user"]).status_code == 403
    assert setup["client"].get("/admin/dashboard/summary").status_code == 401


def test_traffic_endpoint(setup):
    # 이 요청 자체가 집계에 들어간다(운영자 토큰은 test 그룹이라 is_test → test_requests 로)
    r = _get(setup, "/admin/dashboard/traffic?minutes=5", setup["operator"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["window_minutes"] == 5 and len(body["series"]) == 5
    assert body["pod"]["hostname"] and body["pod"]["env"] == "test"
    assert set(body["status"]) == {"2xx", "3xx", "4xx", "5xx"}
