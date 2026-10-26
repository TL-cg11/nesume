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
    from runner import core  # noqa: E402
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
        return CurrentUser(sub=accounts.sub(role), role=ROLES[role])

    app.dependency_overrides[get_current_user] = current
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
        "B19-SHARE-03": ("block", 404, True)}


def test_llm_channel_reads_audit_log_when_sink_wired(env):
    """감사 로그 저장소를 연결하면 판정을 감사 로그에서 읽는다(link=time 임시 연결)."""
    app, accounts = env
    guard = Guardrail(llm=LlmClient(provider=FakeProvider(reply="다듬었습니다.")), vault=InMemoryVaultStore(),
                      audit=DbAuditSink())
    app.dependency_overrides[writing_router.get_guardrail] = lambda: guard
    results, _ = core.run(TestClient(app), accounts, DbSeeder(accounts), _scenarios("A10-SENS-01", "A10-SENS-05"),
                          delay=0.01)
    by = {r.id: r for r in results}
    assert by["A10-SENS-01"].judged_by == "audit" and by["A10-SENS-01"].actual_decision == "block"
    assert by["A10-SENS-05"].judged_by == "audit" and by["A10-SENS-05"].actual_decision == "allow"
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
