"""A7 STAR 분석 + 1차·2차 조립 테스트."""

from __future__ import annotations

import pytest

from app.features.writing import (
    MAX_LLM_SUGGESTIONS,
    SEP,
    analyze,
    guidance,
    improve,
    parse_llm_suggestions,
)
from app.guardrail import Chunk, Guardrail, LlmClient
from app.pii import InMemoryVaultStore
from tests.guardrail.fakes import FakeProvider

FULL = ("2025년 교내 프로젝트에서 예약 지연 문제를 맡게 되었습니다. "
        "응답 구조를 직접 설계했고 캐시를 도입했습니다. "
        "그 결과 응답시간을 40% 단축했습니다.")
THIN = "열심히 했습니다. 많은 것을 배웠습니다."


def _guard(reply: str = "") -> Guardrail:
    return Guardrail(
        llm=LlmClient(provider=FakeProvider(reply=reply)),
        vault=InMemoryVaultStore(),
    )


# ---------------------------------------------------------------- STAR 분석

def test_full_text_has_all_elements() -> None:
    a = analyze(FULL)
    assert a.present == frozenset({"S", "T", "A", "R"})
    assert a.missing == ()


def test_thin_text_has_none() -> None:
    a = analyze(THIN)
    assert a.count == 0
    assert len(a.missing) == 4


@pytest.mark.parametrize(
    "text,element",
    [
        ("2025년에 있었던 일입니다", "S"),
        ("동아리 프로젝트에서 겪은 일입니다", "S"),
        ("성능 개선이라는 목표를 맡게 되었습니다", "T"),
        ("제 역할은 데이터 정리였습니다", "T"),
        ("API를 직접 구현했습니다", "A"),
        ("팀원을 설득했습니다", "A"),
        ("비용을 30% 절감했습니다", "R"),
        ("교내 대회에서 수상했습니다", "R"),
    ],
)
def test_element_clues(text: str, element: str) -> None:
    assert element in analyze(text).present, f"{element} 를 놓침: {text}"


def test_empty_text() -> None:
    a = analyze("")
    assert a.count == 0 and a.missing == ("S", "T", "A", "R")


def test_evidence_points_into_the_text() -> None:
    a = analyze(FULL)
    for element, (start, end) in a.evidence.items():
        assert 0 <= start < end <= len(FULL), element


def test_guidance_asks_questions_for_missing_only() -> None:
    a = analyze("2025년 프로젝트에서 API를 직접 구현했습니다")
    g = guidance(a, "x")
    assert {s.rule_id for s in g} == {f"WR_STAR_{e}" for e in a.missing}
    for s in g:
        assert s.suggested == "", "무엇을 쓸지는 글쓴이만 압니다"
        assert "?" in s.reason or "보십시오" in s.reason


# ---------------------------------------------------------------- 모델 응답 해석

def test_parses_valid_lines() -> None:
    text = "저는 최선을 다했고 결과도 좋았습니다."
    reply = f"최선을 다했고{SEP}문제를 끝까지 파고들었고{SEP}구체적입니다"
    (s,) = parse_llm_suggestions(reply, text, taken=[])

    assert s.source == "llm"
    assert text[s.start : s.end] == "최선을 다했고"
    assert s.suggested == "문제를 끝까지 파고들었고"


def test_drops_suggestions_whose_original_is_absent() -> None:
    """★ 모델이 글에 없는 조각을 가리키면 버립니다. 적용하면 엉뚱한 자리가 바뀝니다."""
    reply = f"있지도 않은 문장{SEP}고친 문장{SEP}이유"
    assert parse_llm_suggestions(reply, "전혀 다른 내용입니다.", taken=[]) == []


def test_drops_malformed_lines() -> None:
    reply = "구분자 없는 줄\n\n또 다른 줄"
    assert parse_llm_suggestions(reply, "아무 글", taken=[]) == []


def test_drops_no_op_suggestions() -> None:
    text = "같은 문장입니다."
    reply = f"같은 문장{SEP}같은 문장{SEP}이유"
    assert parse_llm_suggestions(reply, text, taken=[]) == []


def test_rule_suggestions_win_on_overlap() -> None:
    """글을 바꾸는 규칙 제안과 겹치면 규칙을 남깁니다. 근거가 분명한 쪽입니다."""
    from app.features.writing import check

    text = "프로젝트가 진행되어집니다."
    rules = check(text)
    reply = f"진행되어집니다{SEP}진행됩니다{SEP}중복"
    assert parse_llm_suggestions(reply, text, taken=rules) == []


def test_guidance_only_rules_do_not_block_the_model() -> None:
    """★ 안내는 글을 바꾸지 않으니 충돌이 아닙니다.

    "구체적으로 쓰라"는 안내에 모델의 구체적 대안이 따라붙는 것이
    사용자에게 가장 쓸모 있습니다.
    """
    from app.features.writing import check

    text = "저는 최선을 다했습니다."
    rules = check(text)
    assert any(r.rule_id == "WR_CLICHE" and not r.is_replacement for r in rules)

    reply = f"최선을 다했습니다{SEP}병목 구간을 먼저 측정했습니다{SEP}무엇을 했는지 드러납니다"
    (s,) = parse_llm_suggestions(reply, text, taken=rules)
    assert s.suggested == "병목 구간을 먼저 측정했습니다"


def test_caps_the_number_of_suggestions() -> None:
    text = " ".join(f"문장{i}번" for i in range(30))
    reply = "\n".join(f"문장{i}번{SEP}바꾼문장{i}{SEP}이유" for i in range(30))
    assert len(parse_llm_suggestions(reply, text, taken=[])) == MAX_LLM_SUGGESTIONS


# ---------------------------------------------------------------- 조립

@pytest.mark.anyio
async def test_thin_text_also_goes_to_the_model() -> None:
    """요소 수로 2차를 막지 않는다 (2026-10-22 팀 회의 결정).

    이전에는 요소가 2개 이하면 모델을 부르지 않았다. 지금은 부른다.
    """
    provider = FakeProvider()
    guard = Guardrail(llm=LlmClient(provider=provider), vault=InMemoryVaultStore())

    result = await improve(THIN, guard=guard, user_id="u1", role="user")

    assert result.llm_used is True
    assert len(provider.calls) == 1


@pytest.mark.anyio
async def test_missing_star_guidance_is_always_included() -> None:
    """★ 요소 수로 막지 않으므로, 이 안내가 "무엇을 더 써야 하는지" 알리는 유일한 장치다."""
    result = await improve(THIN, guard=_guard(""), user_id="u1", role="user")
    assert {s.rule_id for s in result.suggestions if s.kind == "star"} == {
        "WR_STAR_S", "WR_STAR_T", "WR_STAR_A", "WR_STAR_R"
    }


@pytest.mark.anyio
async def test_guidance_is_included_even_without_the_model() -> None:
    result = await improve(THIN, guard=_guard(""), user_id="u1", role="user", use_llm=False)
    assert any(s.rule_id.startswith("WR_STAR_") for s in result.suggestions)
    assert result.llm_used is False


@pytest.mark.anyio
async def test_full_text_uses_the_model() -> None:
    reply = f"캐시를 도입했습니다{SEP}읽기 비중이 높은 구간에 캐시를 도입했습니다{SEP}무엇을 왜 했는지 드러납니다"
    result = await improve(FULL, guard=_guard(reply), user_id="u1", role="user")

    assert result.llm_used is True
    assert len(result.llm_suggestions) == 1


@pytest.mark.anyio
async def test_use_llm_false_runs_rules_only() -> None:
    provider = FakeProvider()
    guard = Guardrail(llm=LlmClient(provider=provider), vault=InMemoryVaultStore())

    result = await improve(FULL, guard=guard, user_id="u1", role="user", use_llm=False)
    assert result.llm_used is False
    assert provider.calls == []


@pytest.mark.anyio
async def test_blocked_output_still_returns_rule_suggestions() -> None:
    """가드레일이 막아도 1차 결과는 돌려줍니다. 사용자가 빈손으로 끝나지 않습니다."""
    blocked_reply = "키는 AKIAIOSFODNN7EXAMPLE 입니다"
    text = FULL + " 최선을 다했습니다."

    result = await improve(text, guard=_guard(blocked_reply), user_id="u1", role="user")

    assert result.blocked_reason is not None
    assert result.llm_suggestions == []
    assert any(s.rule_id == "WR_CLICHE" for s in result.rule_suggestions)


@pytest.mark.anyio
async def test_goes_through_the_guardrail() -> None:
    """★ 모델을 직접 부르지 않습니다. 토큰화·분류·출력검사가 자동으로 걸립니다."""
    provider = FakeProvider()
    guard = Guardrail(llm=LlmClient(provider=provider), vault=InMemoryVaultStore())

    await improve(FULL + " 이름: 김철수", guard=guard, user_id="u1", role="user")

    (request,) = provider.calls
    assert "김철수" not in request.prompt, "원문이 모델에 그대로 갔습니다"
    assert "[[PERSON_1]]" in request.prompt


@pytest.mark.anyio
async def test_counts_are_reported() -> None:
    result = await improve(THIN, guard=_guard(), user_id="u1", role="user")
    assert sum(result.counts.values()) == len(result.suggestions)


@pytest.mark.anyio
async def test_test_traffic_needs_the_prefix() -> None:
    with pytest.raises(ValueError, match="test-"):
        await improve(FULL, guard=_guard(), user_id="u1", role="user", is_test=True)


def test_llm_suggestions_are_medium_confidence() -> None:
    """모델 제안은 근거를 댈 수 없습니다. 규칙과 같은 무게로 보이면 안 됩니다."""
    text = "저는 최선을 다했습니다."
    reply = f"최선을 다했습니다{SEP}병목을 먼저 측정했습니다{SEP}구체적입니다"
    (s,) = parse_llm_suggestions(reply, text, taken=[])
    assert s.confidence == "medium"
