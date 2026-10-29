"""STAR 모델 판정 · 말투 샘플 리라이팅.

DB·네트워크를 쓰지 않는다. 모델은 가짜를 주입한다.
"""

from __future__ import annotations

import pytest

from app.features.writing import rewrite_service, star_review
from app.features.writing.rewrite import (
    CANDIDATE_COUNT,
    CANDIDATE_MARK,
    SAMPLE_OWN_ENDINGS,
    SAMPLE_RULE,
    RewriteOptionError,
    RewriteOptions,
)
from app.guardrail import Guardrail, LlmClient
from app.pii import InMemoryVaultStore
from tests.guardrail.fakes import FakeProvider

CTX = dict(user_id="u1", role="user", session_id="s1")

TEXT = (
    "2025년 교내 동아리에서 웹 서비스를 만들었습니다. 응답이 느리다는 불만이 많았습니다. "
    "로그를 분석해 느린 쿼리를 찾고 인덱스를 추가했습니다. 응답시간이 40% 줄었습니다."
)


def _guard(reply: str) -> tuple[Guardrail, FakeProvider]:
    provider = FakeProvider(reply=reply)
    return Guardrail(llm=LlmClient(provider=provider), vault=InMemoryVaultStore()), provider


# ---------------------------------------------------------------- STAR 판정

def test_parse_keeps_only_quotes_that_are_in_the_text() -> None:
    reply = (
        "S|||충분|||2025년 교내 동아리에서|||\n"
        "T|||부족|||글에 없는 문장입니다|||목표가 분명하지 않습니다\n"
        "A|||충분|||로그를 분석해 느린 쿼리를 찾고|||\n"
        "R|||부족|||응답시간이 40% 줄었습니다|||무엇이 나아졌는지 덧붙이면 좋습니다\n"
    )
    out = {r.element: r for r in star_review.parse_reply(reply, TEXT)}

    assert out["S"].status == "ok" and out["S"].quote == "2025년 교내 동아리에서"
    assert out["T"].status == "weak" and out["T"].quote is None, "★ 글에 없는 근거는 버린다"
    assert out["R"].comment and out["R"].question, "부족하면 무엇이 부족한지와 질문이 붙는다"
    assert out["A"].comment is None and out["A"].question is None, "충분하면 묻지 않는다"
    assert all(r.source == "llm" for r in out.values())


def test_cell_labels_echoed_by_the_model_are_stripped() -> None:
    """실모델이 "근거 조각 …", "부족한 점 한 문장 …" 처럼 칸 이름을 붙여 왔다."""
    reply = "R|||부족|||근거 조각 응답시간이 40% 줄었습니다.|||부족한 점 한 문장 무엇이 나아졌는지 없습니다."
    r = {x.element: x for x in star_review.parse_reply(reply, TEXT)}["R"]
    assert r.quote == "응답시간이 40% 줄었습니다."
    assert r.comment == "무엇이 나아졌는지 없습니다."


def test_unreadable_elements_fall_back_to_rules() -> None:
    out = star_review.parse_reply("S|||충분|||2025년|||\n엉뚱한 줄", TEXT)
    sources = {r.element: r.source for r in out}
    assert sources["S"] == "llm"
    assert {sources[e] for e in "TAR"} == {"rule"}
    assert [r.element for r in out] == ["S", "T", "A", "R"], "순서는 항상 STAR"


@pytest.mark.anyio
async def test_review_calls_the_model_once() -> None:
    guard, provider = _guard("S|||충분|||2025년|||\nT|||없음||||||과제가 없습니다\n")
    result = await star_review.review(TEXT, guard=guard, **CTX)
    assert len(provider.calls) == 1
    assert result.llm_used
    assert {r.element: r.status for r in result.elements}["T"] == "missing"


@pytest.mark.anyio
async def test_review_without_a_provider_uses_rules() -> None:
    result = await star_review.review(TEXT, guard=Guardrail(), **CTX)
    assert result.llm_unavailable
    assert all(r.source == "rule" for r in result.elements)


# ---------------------------------------------------------------- 말투 샘플

@pytest.fixture
def no_template(monkeypatch):
    monkeypatch.setattr(rewrite_service.templates_service, "get_active_template",
                        lambda db, name: None)
    monkeypatch.setattr(rewrite_service.profile_service, "get", lambda owner_id, *, store: None)


SAMPLE = (
    "요즘은 아침마다 짧게 글을 쓴다. 거창한 건 아니고, 어제 한 일을 세 줄로 적는다. "
    "적다 보면 생각보다 한 일이 많다는 걸 알게 된다. 그래서 계속 쓴다. 연락은 010-1234-5678."
)


def _reply(bodies: list[str]) -> str:
    return "\n\n".join(f"{CANDIDATE_MARK}{i}\n{b}" for i, b in enumerate(bodies, 1))


@pytest.mark.anyio
async def test_sample_goes_to_the_model_masked(no_template) -> None:
    """★ 샘플도 본문과 같이 치환된다. 샘플 속 연락처가 모델로 가면 안 된다."""
    guard, provider = _guard(_reply(["다시 쓴 글입니다."] * CANDIDATE_COUNT))
    result = await rewrite_service.rewrite(
        None, TEXT, RewriteOptions(), guard=guard, store=None, style_sample=SAMPLE, **CTX
    )
    prompt = provider.calls[0].prompt
    assert "말투 샘플" in prompt and "거창한 건 아니고" in prompt
    assert "010-1234-5678" not in prompt
    assert SAMPLE_RULE in result.instructions
    assert len(result.candidates) == CANDIDATE_COUNT


@pytest.mark.anyio
async def test_candidate_with_numbers_from_elsewhere_is_dropped(no_template) -> None:
    """샘플의 숫자가 섞이면 이 경험의 사실이 아니다. 후보째 버린다."""
    guard, _ = _guard(_reply([
        "응답시간이 40% 줄었습니다.",
        "응답시간이 40% 줄었고 3명이 함께했습니다.",
        "응답시간이 40% 줄었습니다. 그래서 배웠습니다.",
    ]))
    result = await rewrite_service.rewrite(
        None, TEXT, RewriteOptions(), guard=guard, store=None, style_sample=SAMPLE, **CTX
    )
    assert len(result.candidates) == 2
    assert any("숫자" in n for n in result.notices)


@pytest.mark.anyio
async def test_candidate_that_keeps_the_sample_endings_is_dropped(no_template) -> None:
    """샘플 끝맺음(했다)이 문체 지시를 이기는 일이 잦았다. 고른 문체가 아니면 뺀다."""
    guard, _ = _guard(_reply([
        "응답시간이 40% 줄었습니다.",
        "응답시간이 40% 줄었다.",
        "결국 응답시간이 40% 줄었습니다.",
    ]))
    result = await rewrite_service.rewrite(
        None, TEXT, RewriteOptions(tone="formal"), guard=guard, store=None,
        style_sample=SAMPLE, **CTX
    )
    assert [c.body for c in result.candidates] == [
        "응답시간이 40% 줄었습니다.", "결국 응답시간이 40% 줄었습니다.",
    ]
    assert any("합니다체" in n for n in result.notices)


def test_sample_measures_are_numbers_and_whitelisted_words_only() -> None:
    m = rewrite_service.sample_measures(SAMPLE, TEXT)
    assert "평균" in m and "그래서" in m
    assert "010" not in m and "거창한" not in m, "샘플 내용어는 치환을 거치지 않으므로 넣지 않는다"


@pytest.mark.anyio
async def test_too_short_sample_is_rejected(no_template) -> None:
    guard, provider = _guard("")
    with pytest.raises(RewriteOptionError):
        await rewrite_service.rewrite(
            None, TEXT, RewriteOptions(), guard=guard, store=None, style_sample="짧아요.", **CTX
        )
    assert provider.calls == []


# ---------------------------------------------------------------- 끝맺음도 샘플을 따른다 (2026-10-29)

@pytest.mark.anyio
async def test_without_a_tone_endings_follow_the_sample(no_template) -> None:
    """화면은 끝맺음을 고르지 않는다. 샘플(했다체)이 기준이 되어 합니다체 후보가 빠진다."""
    guard, provider = _guard(_reply([
        "응답시간이 40% 줄었다.",
        "응답시간이 40% 줄었습니다.",
        "결국 응답시간이 40% 줄었다.",
    ]))
    result = await rewrite_service.rewrite(
        None, TEXT, RewriteOptions(tone=None), guard=guard, store=None,
        style_sample=SAMPLE, **CTX
    )
    prompt = provider.calls[0].prompt
    # ★ "샘플과 같게" 만으로는 모델이 따르지 않아(10-29 실측) 판정한 문체 이름으로 지시한다
    assert "반드시 했다체로" in prompt
    assert "합니다체" not in prompt
    assert [c.body for c in result.candidates] == [
        "응답시간이 40% 줄었다.", "결국 응답시간이 40% 줄었다.",
    ]
    assert any("했다체" in n for n in result.notices)


@pytest.mark.anyio
async def test_mixed_sample_falls_back_to_a_general_instruction(no_template) -> None:
    """샘플 문체가 섞여 있으면 하나로 정할 수 없다. 막연한 지시로 두고 문체로 거르지 않는다."""
    mixed = (
        "처음엔 막막했다. 그래서 하나씩 뜯어봤어요. 작게 쪼개서 고쳤습니다. "
        "그리고 확인했다. 그 덕분에 끝낼 수 있었어요. 결국 방향이 중요합니다. " * 2
    )
    guard, provider = _guard(_reply(["다시 썼습니다.", "다시 썼다.", "다시 썼어요."]))
    result = await rewrite_service.rewrite(
        None, TEXT, RewriteOptions(tone=None), guard=guard, store=None,
        style_sample=mixed, **CTX
    )
    assert SAMPLE_OWN_ENDINGS in provider.calls[0].prompt
    assert len(result.candidates) == CANDIDATE_COUNT


@pytest.mark.anyio
async def test_without_a_tone_or_sample_the_default_tone_is_used(no_template) -> None:
    guard, provider = _guard(_reply(["다시 쓴 글입니다."] * CANDIDATE_COUNT))
    result = await rewrite_service.rewrite(
        None, TEXT, RewriteOptions(tone=None), guard=guard, store=None, **CTX
    )
    assert "합니다체로 씁니다" in provider.calls[0].prompt
    assert "합니다체" in result.instructions


@pytest.mark.anyio
async def test_all_candidates_filtered_says_why(no_template) -> None:
    guard, _ = _guard(_reply(["응답시간이 40% 줄었습니다."] * CANDIDATE_COUNT))
    result = await rewrite_service.rewrite(
        None, TEXT, RewriteOptions(tone=None), guard=guard, store=None,
        style_sample=SAMPLE, **CTX
    )
    assert result.candidates == ()
    assert any("조건에 맞는 후보가 없어" in n for n in result.notices)
    assert not any("형식대로" in n for n in result.notices), "형식 오류가 아니다"


@pytest.mark.anyio
async def test_one_paragraph_original_gives_one_paragraph_candidates(no_template) -> None:
    """짧게 끊는 샘플을 따르면 모델이 문장마다 줄을 바꿨다. 원문이 한 문단이면 붙인다."""
    guard, _ = _guard(_reply(["응답이 느렸다. \n그래서 고쳤다.\n응답시간이 40% 줄었다."] * CANDIDATE_COUNT))
    result = await rewrite_service.rewrite(
        None, TEXT, RewriteOptions(tone=None), guard=guard, store=None,
        style_sample=SAMPLE, **CTX
    )
    assert result.candidates[0].body == "응답이 느렸다. 그래서 고쳤다. 응답시간이 40% 줄었다."
