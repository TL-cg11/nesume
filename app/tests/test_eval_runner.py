"""B16 평가 러너 (part2_guide 4.50): 시트 → API 투입 → 판정 비교 → 지표·CI 기준."""
import sys
import uuid
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

EVAL = Path("/eval")
pytestmark = pytest.mark.skipif(not (EVAL / "runner").exists(), reason="eval/ 미마운트")
sys.path.insert(0, str(EVAL))

from app.auth import CurrentUser, Role, get_current_user  # noqa: E402
from app.features.audit.sink import DbAuditSink  # noqa: E402
from app.features.share.router import mentor_router, owner_router  # noqa: E402
from app.features.writing import router as writing_router  # noqa: E402
from app.guardrail import Guardrail, LlmClient  # noqa: E402
from app.main import create_app  # noqa: E402
from app.pii import InMemoryVaultStore  # noqa: E402
from tests.guardrail.fakes import FakeProvider  # noqa: E402

if (EVAL / "runner").exists():
    from runner import core, seed  # noqa: E402
    from runner.seed import DbSeeder  # noqa: E402

ROLES = {"user": Role.USER, "user2": Role.USER, "mentor": Role.MENTOR, "operator": Role.OPERATOR,
         "system": Role.SYSTEM}


class FakeAccounts:
    """토큰 'fake-<role>' ↔ 테스트마다 새 sub."""

    def __init__(self):
        self.subs = {r: f"run-{r}-{uuid.uuid4().hex[:6]}" for r in ROLES}

    def token(self, role):
        return f"fake-{role}"

    def sub(self, role):
        return self.subs[role]


@pytest.fixture
def env():
    accounts = FakeAccounts()
    app = create_app()
    for r in (owner_router, mentor_router):  # main.py 등록(D) 전이라 테스트 앱에 붙인다
        app.include_router(r)

    def current(request: Request):
        role = request.headers["Authorization"].removeprefix("Bearer fake-")
        # 시드 계정은 모두 test 그룹(D6) → is_test는 토큰에서 온다(A PR #11). 가짜 계정도 같게 맞춘다
        return CurrentUser(sub=accounts.sub(role), role=ROLES[role], is_test=True)

    app.dependency_overrides[get_current_user] = current
    # B11 조회는 운영자 MFA 필수. 러너 테스트는 MFA 검사를 끈다(staging은 TOTP 등록 계정 사용, B16.md)
    from app.config import get_settings
    app.dependency_overrides[get_settings] = lambda: get_settings().model_copy(update={"operator_mfa_required": False})
    yield app, accounts
    app.dependency_overrides.clear()


def _scenarios(*prefixes):
    return [s for s in core.load_sheet(EVAL / "scenarios_sheet.yaml") if s["id"].startswith(prefixes)]


def test_api_channel_b19_against_real_api(env):
    app, accounts = env
    results, m = core.run(TestClient(app), accounts, DbSeeder(accounts), _scenarios("B19"))
    api = {r.id: r for r in results if r.channel == "api"}
    assert {i: (r.actual_decision, r.http_status, r.match) for i, r in api.items()} == {
        "B19-SHARE-01": ("block", 404, True), "B19-SHARE-02": ("block", 404, True),
        "B19-SHARE-03": ("block", 404, True), "B19-SHARE-04": ("block", 404, True),
        "B19-SHARE-05": ("allow", 200, True)}  # 5건 모두 api(4.61)


class _FakeEmbedder:
    def embed(self, texts):
        return [[0.0] * 1024 for _ in texts]


def test_user_resume_without_embedder_is_unverified(env):
    """C11-05: 임베더가 없으면 자소서만 만들고 인덱싱을 건너뛰며, 결과에 '미확인'으로 남긴다(D bge-m3 대기)."""
    app, accounts = env
    results, _ = core.run(TestClient(app), accounts, DbSeeder(accounts), _scenarios("C11-AUTHZ-05"))
    assert seed.RETRIEVAL_SKIPPED in results[0].checks_unverified


def test_user_resume_is_indexed_tokenized_with_embedder(env):
    """임베더가 있으면 저장본(토큰화된 본문)을 개인 인덱스에 넣는다 — 연락처 원문은 인덱스에 없다."""
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models.embedding import UserProfileEmbedding
    _, accounts = env
    s = _scenarios("C11-AUTHZ-05")[0]
    values = DbSeeder(accounts, embedder=_FakeEmbedder()).prepare(s)
    assert "_unverified" not in values
    with SessionLocal() as db:
        row = db.scalar(select(UserProfileEmbedding).where(
            UserProfileEmbedding.source_id == uuid.UUID(values["user_resume_id"])))
    assert row.owner_id == accounts.sub("user") and row.source_type == "resume" and row.grade == "personal"
    assert "010-2345-6789" not in row.content and "[[PHONE" in row.content


def test_response_excludes_catches_leak(env):
    """대조군: 응답 본문에 나오면 안 되는 문장이 실제로 있으면 불일치로 잡는다(05가 '항상 통과'하지 않게)."""
    app, accounts = env
    s = dict(_scenarios("B19-SHARE-05")[0])
    s["expect_checks"] = {**s["expect_checks"], "response_excludes": ["평가 러너 시드 문단"]}  # 공유 시점 v1 본문
    results, _ = core.run(TestClient(app), accounts, DbSeeder(accounts), [s])
    assert results[0].http_status == 200 and not results[0].match
    assert results[0].checks_failed == ["응답에 '평가 러너 시드 문단' 있음"]


def test_llm_channel_reads_audit_log_when_sink_wired(env):
    """감사 로그 저장소를 연결하면 판정을 감사 로그에서 읽는다(link=time 임시 연결)."""
    app, accounts = env
    guard = Guardrail(llm=LlmClient(provider=FakeProvider(reply="다듬었습니다.")), vault=InMemoryVaultStore(),
                      audit=DbAuditSink())
    app.dependency_overrides[writing_router.get_guardrail] = lambda: guard
    results, _ = core.run(TestClient(app), accounts, DbSeeder(accounts), _scenarios("A10-SENS-01", "A10-SENS-05"),
                          delay=0.01)
    by = {r.id: r for r in results}
    assert all(r.link == "request_id" for r in results)  # X-Request-ID로 정확히 연결
    assert by["A10-SENS-01"].judged_by == "audit" and by["A10-SENS-01"].actual_decision == "block"
    assert by["A10-SENS-05"].judged_by == "audit" and by["A10-SENS-05"].actual_decision == "mask"
    assert all(r.endpoint == "POST /writing/proofread" for r in results)
    # 대체 표시는 시트의 feature가 러너 엔드포인트 표에 없을 때만(A10 feature 반영 전후 모두 성립)
    assert all(r.substituted == (r.feature not in core.ENDPOINTS) for r in results)
    assert by["A10-SENS-05"].checks_unverified == ["prompt_free_of"]


def test_llm_channel_falls_back_to_response_without_audit(env):
    """지금 main처럼 감사 로그가 없으면 응답의 blocked_reason으로 판정하고 그렇게 표시한다."""
    app, accounts = env
    guard = Guardrail(llm=LlmClient(provider=FakeProvider(reply="다듬었습니다.")), vault=InMemoryVaultStore())
    app.dependency_overrides[writing_router.get_guardrail] = lambda: guard
    results, m = core.run(TestClient(app), accounts, DbSeeder(accounts), _scenarios("A10-SENS-01"))
    r = results[0]
    assert r.judged_by == "response" and r.actual_decision == "block" and r.match
    assert m["judged_by"]["response"] == 1


def _r(cat, exp, act, known=False):
    return core.Result(id="x", source="T", category=cat, channel="llm", role="user", feature="",
                       expect_decision=exp, actual_decision=act, match=exp == act, known_miss=known)


def test_metrics_and_gate():
    attack = [_r("sensitive", "block", "block")] * 19 + [_r("exfiltration", "block", "allow", known=True)]
    normal = [_r("normal", "allow", "allow")] * 20
    m = core.metrics(attack + normal)
    assert m["block_rate"] == 0.95 and m["overblock_rate"] == 0.0 and m["gate_passed"]
    assert m["excluding_known_miss"]["block_rate"] == 1.0
    m2 = core.metrics(attack + normal + [_r("normal", "allow", "block")] * 2)
    assert m2["overblock_rate"] == pytest.approx(2 / 22, abs=1e-4) and not m2["gate_passed"]  # 과차단 9% > 5%
    m3 = core.metrics([_r("authz", "mask", "allow")] + normal)
    assert m3["mask_accuracy"] == 0.0 and not m3["gate_passed"]


def test_results_csv(env):
    app, accounts = env
    results, _ = core.run(TestClient(app), accounts, DbSeeder(accounts), _scenarios("B19-SHARE-01"))
    text = core.render_csv(results)
    assert text.startswith("﻿") and "B19-SHARE-01" in text and text.splitlines()[0].lstrip("﻿") == ",".join(
        core.RESULT_COLUMNS)


def test_runner_traffic_is_marked_test_and_uses_one_session_per_scenario(env):
    app, accounts = env
    guard = Guardrail(llm=LlmClient(provider=FakeProvider(reply="다듬었습니다.")), vault=InMemoryVaultStore(),
                      audit=DbAuditSink())
    app.dependency_overrides[writing_router.get_guardrail] = lambda: guard
    multi = [s for s in core.load_sheet(EVAL / "scenarios_sheet.yaml") if len(s["turns"]) > 1][:1]
    core.run(TestClient(app), accounts, DbSeeder(accounts), multi)
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import AuditLog
    with SessionLocal() as db:
        logs = db.scalars(select(AuditLog).where(AuditLog.user_id == accounts.sub(multi[0]["role"]))).all()
    assert len(logs) == len(multi[0]["turns"]) and all(log.is_test for log in logs)
    assert len({log.session_id for log in logs}) == 1 and logs[0].session_id.startswith(f"test-{multi[0]['id']}-")


def test_audit_api_request_id_filter(env):
    app, accounts = env
    c = TestClient(app)
    res = c.get("/audit-logs", params={"request_id": str(uuid.uuid4())}, headers={"Authorization": "Bearer fake-operator"})
    assert res.status_code == 200 and res.json() == []
    assert c.get("/audit-logs", params={"request_id": "x"},
                 headers={"Authorization": "Bearer fake-operator"}).status_code == 422


def test_seeder_reuses_base_resume_under_resume_limit(env):
    """시트 전체를 돌려도 시드 자소서가 50개 상한에 걸리지 않는다(사전 조건 없는 시나리오는 공용 자소서)."""
    app, accounts = env
    seeder = DbSeeder(accounts)
    plain = {"preconditions": {}}
    ids = {seeder.prepare(plain)["resume_id"] for _ in range(60)}
    assert len(ids) == 1


def test_eval_waf_token_header_only_when_set():
    """D17 WAF 요청 수 제한 예외 헤더. 값이 없으면(로컬) 붙이지 않는다."""
    from runner.__main__ import EVAL_TOKEN_HEADER, client_headers
    assert client_headers({}) == {}
    assert client_headers({"EVAL_WAF_TOKEN": "  "}) == {}
    assert client_headers({"EVAL_WAF_TOKEN": "t0k"}) == {EVAL_TOKEN_HEADER: "t0k"}


def test_eval_waf_token_not_written_to_results(env, tmp_path, monkeypatch):
    """헤더 값은 결과 CSV·요약 JSON·표준 출력에 남지 않는다."""
    from runner import __main__ as entry
    from runner import core
    secret = f"waf-{uuid.uuid4()}"
    monkeypatch.setenv("EVAL_WAF_TOKEN", secret)
    seen = {}

    def fake_run(client, *a, **k):
        seen["header"] = client.headers.get(entry.EVAL_TOKEN_HEADER)
        return [], core.metrics([])

    monkeypatch.setattr(core, "run", fake_run)
    monkeypatch.setattr(entry.CognitoAccounts, "from_env", classmethod(lambda cls: None))
    monkeypatch.setattr(entry, "DbSeeder", lambda accounts: None)
    entry.main(["--base-url", "http://dev.example", "--out-dir", str(tmp_path), "--only", "NONE"])
    assert seen["header"] == secret
    for f in tmp_path.iterdir():
        assert secret not in f.read_text(encoding="utf-8")
