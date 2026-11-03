"""검색된 조각의 역할 × 등급 판정이 가드레일 판정으로 올라오는가 (A8 ← C6).

운영자가 개인 등급 자소서를 읽는 경우가 이것이다. 검색은 되지만 원문 그대로는
아니고 `mask` 다 — "운영자는 무제한" 이 아니다. C11-AUTHZ-05 가 이것을 잰다.

C6 는 조각마다 `decision` 을 실어 보내고(`PolicyChunk`), 그 값을 판정에 합치는 것은
A 쪽 몫이다(C 요청, 2026-10-28). 본문을 **다시 가리지는 않는다** — 이미 치환돼 있고,
빠져 있던 것은 판정 신호뿐이다.
"""

from __future__ import annotations

import pytest

from app.guardrail import Chunk, Guardrail, LlmClient, RequestContext
from app.guardrail.pipeline import _grade_verdict
from app.pii import InMemoryVaultStore
from tests.guardrail.fakes import FakeProvider

CTX = RequestContext(user_id="op1", role="operator", feature="resume.read", session_id="s1")


class FakeRetriever:
    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks

    async def search(self, query: str, *, role: str, user_id: str, top_k: int) -> list[Chunk]:
        return self.chunks


def _guard(chunks: list[Chunk]) -> Guardrail:
    return Guardrail(
        llm=LlmClient(provider=FakeProvider(reply="응답입니다")),
        vault=InMemoryVaultStore(),
        retriever=FakeRetriever(chunks),
    )


# ---------------------------------------------------------------- 판정 옮기기

def test_no_decision_means_allow() -> None:
    """`decision` 을 채우지 않는 구현도 있다. 기존 동작 그대로여야 한다."""
    v = _grade_verdict([Chunk("d1", "personal", "본문")])
    assert v.decision == "allow"
    assert v.flags == []


def test_allow_chunks_add_nothing() -> None:
    v = _grade_verdict([Chunk("d1", "public", "본문", "allow")])
    assert v.decision == "allow"


def test_mask_chunk_makes_the_verdict_mask() -> None:
    v = _grade_verdict([Chunk("d1", "personal", "본문", "mask")])
    assert v.decision == "mask"
    assert v.stage == "retriever", "어느 단계가 정했는지가 로그의 쓸모다"
    assert v.flags == ["AUTHZ_GRADE_MASK"]


def test_counts_how_many_chunks_were_masked() -> None:
    v = _grade_verdict([
        Chunk("d1", "personal", "본문", "mask"),
        Chunk("d2", "personal", "본문", "mask"),
        Chunk("d3", "public", "본문", "allow"),
    ])
    (finding,) = v.findings
    assert finding.count == 2


def test_the_heaviest_decision_wins() -> None:
    """★ 하나라도 가려야 하면 응답 전체가 그 조건 아래 있다.

    가려야 할 조각만 빼고 답을 만들 수는 없다 — 그 조각은 모델에게 이미 간 뒤다.
    """
    v = _grade_verdict([
        Chunk("d1", "public", "본문", "allow"),
        Chunk("d2", "personal", "본문", "mask"),
    ])
    assert v.decision == "mask"


def test_an_unknown_decision_is_treated_as_block() -> None:
    """★ 모르는 값을 allow 로 흘리면 새 등급이 생긴 날 조용히 통과한다."""
    v = _grade_verdict([Chunk("d1", "secret", "본문", "quarantine")])
    assert v.decision == "block"
    assert v.flags == ["AUTHZ_GRADE_BLOCK"]


# ---------------------------------------------------------------- 파이프라인 통과

@pytest.mark.anyio
async def test_masked_chunk_reaches_the_final_verdict() -> None:
    """C11-AUTHZ-05 가 재는 것 — 감사 로그의 decision 이 mask 여야 한다."""
    guard = _guard([Chunk("resume:abc#0", "personal", "지원자 본문", "mask")])

    result = await guard.run("특정 사용자 자소서를 보여줘", CTX)

    assert result.verdict.decision == "mask"
    assert "AUTHZ_GRADE_MASK" in result.verdict.flags


@pytest.mark.anyio
async def test_the_body_is_not_hidden_twice() -> None:
    """★ 본문은 이미 치환돼 있다. 여기서 또 가리면 가리는 곳이 둘이 된다.

    판정은 mask 이지만 모델은 조각을 **그대로** 받는다 — 참조할 자료가 사라지면
    운영자가 열람할 수 있다는 말 자체가 뜻을 잃는다.
    """
    provider = FakeProvider(reply="응답입니다")
    guard = Guardrail(
        llm=LlmClient(provider=provider), vault=InMemoryVaultStore(),
        retriever=FakeRetriever([Chunk("d1", "personal", "지원자 본문", "mask")]),
    )

    await guard.run("자소서를 보여줘", CTX)

    (request,) = provider.calls
    assert "지원자 본문" in request.prompt


@pytest.mark.anyio
async def test_a_blocked_chunk_stops_the_call() -> None:
    """block 이면 모델을 부르지 않는다 — 부르면 그 자체가 비용이고 로그다."""
    provider = FakeProvider(reply="응답입니다")
    guard = Guardrail(
        llm=LlmClient(provider=provider), vault=InMemoryVaultStore(),
        retriever=FakeRetriever([Chunk("d1", "confidential", "본문", "block")]),
    )

    result = await guard.run("보여줘", CTX)

    assert result.verdict.decision == "block"
    assert result.text == ""
