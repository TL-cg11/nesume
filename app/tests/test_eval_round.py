"""B21 측정 라운드 실행기 (part2_guide 4.58). 평소 테스트에서는 건너뛴다.

로컬에서 앱을 그대로 띄워(격리 테스트 DB) 시트 전체를 실제 API로 투입하고, 결과를 eval/reports/<라운드>/에 쓴다.
    docker compose run --rm -v "$PWD/eval:/eval_rw" -e EVAL_ROUND=round1 test tests/test_eval_round.py -q -s
조건: 감사 로그·대화 이력은 A 연결 구성 그대로, B 공유·템플릿 라우터 포함(D 등록 후와 같음), 모델 응답은 가짜(고정 문장).
"""
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROUND = os.environ.get("EVAL_ROUND")
OUT = Path("/eval_rw/reports")
pytestmark = pytest.mark.skipif(not ROUND or not OUT.parent.exists(), reason="EVAL_ROUND 미지정(측정 라운드 전용)")


def test_measure_round(env):  # noqa: F811
    from app.features.audit.sink import DbAuditSink
    from app.features.templates.router import router as templates_router
    from app.guardrail import Guardrail, LlmClient
    from app.guardrail import fastapi as gfa
    from app.guardrail.multiturn import InMemoryTurnStore
    from app.pii import InMemoryVaultStore
    from tests.guardrail.fakes import FakeProvider
    from tests.test_eval_runner import EVAL, DbSeeder, core

    app, accounts = env
    app.include_router(templates_router)
    guard = Guardrail(llm=LlmClient(provider=FakeProvider(reply="문장을 다듬었습니다.")), vault=InMemoryVaultStore(),
                      audit=DbAuditSink(), history=InMemoryTurnStore())
    app.dependency_overrides[gfa.get_guardrail] = lambda: guard
    scenarios = core.load_sheet(EVAL / "scenarios_sheet.yaml")
    results, m = core.run(TestClient(app), accounts, DbSeeder(accounts), scenarios)

    out = OUT / ROUND
    out.mkdir(parents=True, exist_ok=True)
    meta = {"round": ROUND, "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "conditions": "local in-process app, isolated test DB, audit+history wired, B share/template routers, "
                          "fake LLM reply", "scenarios": len(scenarios)}
    (out / "results.csv").write_text(core.render_csv(results), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps({"meta": meta, "metrics": m}, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    print(core.render_summary(m))


from tests.test_eval_runner import env  # noqa: E402,F401  (픽스처 재사용)
