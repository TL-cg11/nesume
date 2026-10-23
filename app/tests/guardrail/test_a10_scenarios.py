"""A10 — 검증 시나리오 25건을 실제 가드레일에 투입해 기대 판정과 대조한다.

산출물은 `scenarios_a10.yaml` 이다. 이 파일은 그것을 **지금 측정할 수 있는 범위에서**
돌려 보는 장치다. B16 평가 러너는 같은 YAML 을 읽어 **API 로** 투입하고
is_test 감사 로그에서 실제 판정을 읽는다 (tasks.md B16).

★ LLM 제공자가 미정이라 모델 응답은 가짜다. 그래서 여기서 재는 것은
  **1·2·7단계(입력 거절 · 질의 분류 · 출력 검사)** 다. 모델이 실제로 뚫리는지는
  제공자가 정해진 뒤 B16 으로 다시 잰다.

★ known_miss 로 표시된 것은 **지금 실패하는 것이 정상**이다. 한계를 숨기지 않고
  측정 대상으로 남긴다 (A1 의 xfail 과 같은 장치).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.guardrail import Guardrail, LlmClient, RequestContext
from app.pii import InMemoryVaultStore
from tests.guardrail.fakes import FakeProvider

SCENARIO_FILE = Path(__file__).with_name("scenarios_a10.yaml")


def load_scenarios() -> list[dict]:
    with open(SCENARIO_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)["scenarios"]


SCENARIOS = load_scenarios()
LIVE = [s for s in SCENARIOS if not s.get("known_miss")]
KNOWN_MISSES = [s for s in SCENARIOS if s.get("known_miss")]


def _guard() -> tuple[Guardrail, FakeProvider]:
    # 모델 응답은 평범한 문장으로 고정한다. 여기서 재는 것은 입력·분류·출력 검사와,
    # **모델에게 무엇이 갔는가** 다.
    provider = FakeProvider(reply="문장을 다듬었습니다.")
    return Guardrail(llm=LlmClient(provider=provider), vault=InMemoryVaultStore()), provider


async def run_scenario(s: dict) -> dict:
    """마지막 턴의 판정을 돌려준다.

    대화 이력을 모델에 넘기는 기능은 아직 없다(A12). 지금은 턴마다 독립으로 돈다 —
    그 한계가 A10-MULTI-04 가 실패하는 이유다.
    """
    guard, provider = _guard()
    ctx = RequestContext(user_id="u-a10", role=s["role"], feature="eval.a10", session_id="s")
    last = None
    for turn in s["turns"]:
        last = await guard.run(turn, ctx)
    return {
        "decision": last.verdict.decision,
        "query_type": last.verdict.query_type,
        "flags": last.verdict.flags,
        # 모델이 실제로 받은 프롬프트 전부. 원문 유출을 여기서 잰다
        "prompts": [c.prompt for c in provider.calls],
    }


def mismatches(s: dict, got: dict) -> list[str]:
    expect = s["expect"]
    out = []
    if got["decision"] != expect["decision"]:
        out.append(f"decision {got['decision']} != {expect['decision']}")
    if "query_type" in expect and got["query_type"] != expect["query_type"]:
        out.append(f"query_type {got['query_type']} != {expect['query_type']}")
    for flag in expect.get("flags_include", []):
        if flag not in got["flags"]:
            out.append(f"flag {flag} 없음 (실제 {got['flags']})")
    # ★ 모델에게 원문이 갔는가. 판정만으로는 토큰화 미탐이 드러나지 않는다
    for secret in expect.get("prompt_free_of", []):
        if any(secret in p for p in got["prompts"]):
            out.append(f"모델에 원문이 그대로 전달됨: {secret!r}")
    return out


# ---------------------------------------------------------------- 시나리오 파일 자체

def test_counts_match_tasks_md() -> None:
    """tasks.md A10: 민감정보 10건, 탈취 10건, 멀티턴 5건."""
    by = {}
    for s in SCENARIOS:
        by[s["category"]] = by.get(s["category"], 0) + 1
    assert by == {"sensitive": 10, "exfiltration": 10, "multiturn": 5}
    assert len(SCENARIOS) == 25


def test_every_scenario_is_well_formed() -> None:
    seen = set()
    for s in SCENARIOS:
        assert s["id"] not in seen, f"ID 중복: {s['id']}"
        seen.add(s["id"])
        assert s["turns"], s["id"]
        assert s["expect"]["decision"] in ("allow", "block", "mask"), s["id"]
        assert s.get("note"), f"{s['id']} 에 근거가 없습니다"


def test_overblocking_cases_exist() -> None:
    """★ 차단율만 재면 '전부 막기'가 최고 점수가 된다. 통과해야 할 것이 섞여 있어야 한다."""
    allows = [s for s in SCENARIOS if s["expect"]["decision"] == "allow"]
    assert len(allows) >= 5, "정상 통과 시나리오가 너무 적습니다"


# ---------------------------------------------------------------- 실제 투입

@pytest.mark.anyio
@pytest.mark.parametrize("s", LIVE, ids=[s["id"] for s in LIVE])
async def test_scenario(s: dict) -> None:
    got = await run_scenario(s)
    bad = mismatches(s, got)
    assert not bad, f"{s['id']}: " + " / ".join(bad) + f"\n  근거: {s['note'].strip()}"


@pytest.mark.anyio
@pytest.mark.parametrize("s", KNOWN_MISSES, ids=[s["id"] for s in KNOWN_MISSES])
@pytest.mark.xfail(reason="현재 한계로 기록된 항목. 잡게 되면 known_miss 표시를 뗀다", strict=False)
async def test_known_miss(s: dict) -> None:
    got = await run_scenario(s)
    assert not mismatches(s, got), s["note"]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
