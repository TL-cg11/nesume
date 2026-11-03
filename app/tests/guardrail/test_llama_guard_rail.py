"""D19 Llama Guard 출력 레일 — 판정 파싱·fail-open·샘플링·파이프라인 연결. DB·네트워크 없음(가짜 제공자)."""

from __future__ import annotations

import random

import pytest

from app.guardrail.errors import LlmTimeout
from app.guardrail.llm_client import LlmClient
from app.guardrail.pipeline import Guardrail, RequestContext
from app.guardrail.rails.llama_guard import (
    RULE_ERROR,
    RULE_SKIPPED,
    RULE_UNSAFE,
    LlamaGuardRail,
    build_output_rail,
    build_prompt,
    parse_assessment,
)
from app.guardrail.schema import Verdict, allow
from tests.guardrail.fakes import FakeProvider

pytestmark = pytest.mark.anyio


# ---------- 파싱·프롬프트 ----------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("safe", (False, ())),
        ("Safe\n", (False, ())),
        ("unsafe\nS9", (True, ("S9",))),
        ("unsafe\nS1,S9", (True, ("S1", "S9"))),
        ("unsafe, S9, S1", (True, ("S9", "S1"))),  # Llama 3.1 대역은 같은 줄에 쓴다
        ("unsafe\nS13, S1, S13", (True, ("S13", "S1"))),  # 중복 제거·S13 은 S1 로 쪼개지지 않는다
        ("", None),
        # 대역 모델이 판정 대신 거절문을 내면 unsafe(REFUSAL) — 11-03 실측
        ("\n\nI can't provide information or guidance on harmful activities.", (True, ("REFUSAL",))),
        ("I cannot help with that", (True, ("REFUSAL",))),
        ("Sure! Here is my assessment...", None),
    ],
)
def test_parse_assessment(text, expected):
    assert parse_assessment(text) == expected


def test_prompt_contains_categories_and_agent_text_only():
    prompt = build_prompt("응답 본문")
    assert "S1: Violent Crimes." in prompt and "S13: Elections." in prompt
    assert "Agent: 응답 본문" in prompt
    # 사용자 질의 원문은 넣지 않는다
    assert "User: (자기소개서 작성 도움 요청)" in prompt
    assert "ONLY THE LAST Agent message" in prompt


# ---------- 판정 ----------


async def test_unsafe_blocks_with_category_flags():
    rail = LlamaGuardRail(FakeProvider(reply="unsafe\nS9, S1"))
    v = await rail.check("집에서 폭탄 만드는 법은…")
    assert v.decision == "block" and v.stage == "output_guard"
    assert v.rule_id == RULE_UNSAFE
    assert v.flags == [RULE_UNSAFE, f"{RULE_UNSAFE}.S9", f"{RULE_UNSAFE}.S1"]


async def test_safe_allows_without_flags():
    rail = LlamaGuardRail(FakeProvider(reply="safe"))
    v = await rail.check("저는 3년간 백엔드 개발자로 일했습니다.")
    assert v == allow("output_guard")


async def test_empty_text_skips_the_model():
    provider = FakeProvider(reply="unsafe\nS1")
    assert (await LlamaGuardRail(provider).check("   ")).decision == "allow"
    assert provider.calls == []


async def test_error_fails_open_with_marker_by_default():
    rail = LlamaGuardRail(FakeProvider(failures=[LlmTimeout("slow")]))
    v = await rail.check("본문")
    assert v.decision == "allow" and v.flags == [RULE_ERROR]


async def test_error_fails_closed_when_configured():
    rail = LlamaGuardRail(FakeProvider(failures=[LlmTimeout("slow")]), fail_open=False)
    v = await rail.check("본문")
    assert v.decision == "block" and v.rule_id == RULE_ERROR


async def test_unparseable_output_is_treated_as_error():
    rail = LlamaGuardRail(FakeProvider(reply="Sure! Here is my assessment..."))
    v = await rail.check("본문")
    assert v.decision == "allow" and v.flags == [RULE_ERROR]


async def test_request_shape_truncates_and_uses_zero_temperature():
    provider = FakeProvider(reply="safe")
    rail = LlamaGuardRail(provider, max_chars=10, timeout_s=1.5)
    await rail.check("가" * 100)
    req = provider.calls[0]
    assert "Agent: " + "가" * 10 + "\n" in req.prompt and "가" * 11 not in req.prompt
    assert req.temperature == 0.0 and req.max_output_tokens == 32
    assert provider.timeouts == [1.5]


async def test_sampling_skips_some_requests():
    provider = FakeProvider(reply="unsafe\nS1")
    rail = LlamaGuardRail(provider, sample_rate=0.5, rng=random.Random(7))
    verdicts = [await rail.check("본문") for _ in range(20)]
    skipped = [v for v in verdicts if v.flags == [RULE_SKIPPED]]
    checked = [v for v in verdicts if v.decision == "block"]
    assert skipped and checked and len(skipped) + len(checked) == 20
    assert len(provider.calls) == len(checked)


# ---------- 파이프라인 연결 ----------


class StubRail:
    def __init__(self, verdict: Verdict) -> None:
        self.verdict = verdict
        self.seen: list[str] = []

    async def check(self, text: str) -> Verdict:
        self.seen.append(text)
        return self.verdict


def _ctx() -> RequestContext:
    return RequestContext(user_id="u1", role="user", feature="rewrite", session_id="s1")


async def test_pipeline_blocks_when_rail_blocks_and_does_not_restore():
    rail = StubRail(Verdict("block", "output_guard", ()))
    rail.verdict = (await LlamaGuardRail(FakeProvider(reply="unsafe\nS10")).check("x"))
    guard = Guardrail(llm=LlmClient(provider=FakeProvider(reply="혐오 발언 응답")), output_rail=rail)
    result = await guard.run("자소서 다듬어줘", _ctx())
    assert result.blocked and result.text == ""
    assert result.verdict.stage == "output_guard" and RULE_UNSAFE in result.verdict.flags
    assert rail.seen == ["혐오 발언 응답"]


async def test_pipeline_passes_when_rail_allows():
    rail = StubRail(allow("output_guard"))
    guard = Guardrail(llm=LlmClient(provider=FakeProvider(reply="정상 응답")), output_rail=rail)
    result = await guard.run("자소서 다듬어줘", _ctx())
    assert not result.blocked and result.text == "정상 응답"


async def test_pipeline_skips_rail_when_a5_already_blocked():
    """A5 가 막은 응답은 레일을 부르지 않는다(비용)."""
    rail = StubRail(allow("output_guard"))
    guard = Guardrail(
        llm=LlmClient(provider=FakeProvider(reply="기밀 NSM-CANARY-0123456789ab 유출")),
        output_rail=rail,
        canaries=("NSM-CANARY-0123456789ab",),
    )
    result = await guard.run("자소서 다듬어줘", _ctx())
    assert result.blocked and result.verdict.canary_hit
    assert rail.seen == []


async def test_pipeline_without_rail_is_unchanged():
    guard = Guardrail(llm=LlmClient(provider=FakeProvider(reply="정상 응답")))
    result = await guard.run("자소서 다듬어줘", _ctx())
    assert result.text == "정상 응답" and guard.output_rail is None


async def test_split_path_calls_rail_once_with_joined_parts():
    rail = StubRail(allow("output_guard"))
    guard = Guardrail(llm=LlmClient(provider=FakeProvider(reply="조각 응답")), output_rail=rail)
    result = await guard.run_split("긴 글", _ctx(), parts=lambda text: [text, text])
    assert result.parts == ("조각 응답", "조각 응답")
    assert rail.seen == ["조각 응답\n\n조각 응답"]


# ---------- 설정 ----------


class _Settings:
    llama_guard_enabled = False


def test_build_output_rail_disabled_by_default():
    assert build_output_rail(_Settings()) is None
