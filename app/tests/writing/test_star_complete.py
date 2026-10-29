"""STAR 보완 — 사용자가 허락한 요소만 모델이 써 넣는다.

DB·네트워크를 쓰지 않는다. 모델은 가짜를 주입한다.
"""

from __future__ import annotations

import pytest

from app.features.writing import star_complete
from app.features.writing.star_complete import Fill, StarCompleteError
from app.guardrail import Guardrail, LlmClient
from app.pii import InMemoryVaultStore
from tests.guardrail.fakes import FakeProvider

CTX = dict(user_id="u1", role="user", session_id="s1")
TEXT = "로그를 분석해 느린 쿼리를 찾고 인덱스를 추가했습니다. 서비스가 좋아졌습니다."


def _guard(reply: str) -> tuple[Guardrail, FakeProvider]:
    provider = FakeProvider(reply=reply)
    return Guardrail(llm=LlmClient(provider=provider), vault=InMemoryVaultStore()), provider


def test_prompt_lists_only_what_the_user_chose() -> None:
    prompt = star_complete.build_prompt(
        TEXT, [Fill("S", "write"), Fill("R", "improve", hint="응답이 3초에서 1초로")], ["T"]
    )
    assert "상황" in prompt and "새로 써 넣습니다" in prompt
    assert "응답이 3초에서 1초로" in prompt, "실제 사실이 있으면 그것만 쓰게 한다"
    assert "넣지 않기로" in prompt and "과제" in prompt, "뺀 요소는 만들지 말라고 적는다"
    assert "- 행동 —" not in prompt, "고르지 않은 요소는 건드리지 않는다"


@pytest.mark.parametrize(("fills", "omit"), [
    ([], []),
    ([Fill("X", "write")], []),  # type: ignore[arg-type]
    ([Fill("S", "write")], ["S"]),
    ([Fill("S", "rewrite")], []),  # type: ignore[arg-type]
    ([Fill("S", "write", hint="가" * 301)], []),
])
def test_bad_requests_are_rejected(fills, omit) -> None:
    with pytest.raises(StarCompleteError):
        star_complete.validate(fills, omit)


@pytest.mark.anyio
async def test_server_marks_changes_and_new_numbers() -> None:
    """★ 바뀐 곳은 서버가 비교해 표시하고, 지어낸 숫자는 따로 돌려준다."""
    reply = (
        "2025년 교내 프로젝트에서 로그를 분석해 느린 쿼리를 찾고 인덱스를 추가했습니다. "
        "응답시간이 40% 줄었습니다."
    )
    guard, provider = _guard(reply)
    r = await star_complete.complete(TEXT, [Fill("S", "write"), Fill("R", "improve")], [], guard=guard, **CTX)

    assert len(provider.calls) == 1
    assert r.body == reply
    assert any(s["op"] != "equal" for s in r.segments)
    assert set(r.new_numbers) == {"2025", "40"}


@pytest.mark.anyio
async def test_numbers_from_hints_are_not_flagged() -> None:
    guard, _ = _guard("응답시간이 40% 줄었습니다.")
    r = await star_complete.complete(
        TEXT, [Fill("R", "improve", hint="응답시간 40% 단축")], [], guard=guard, **CTX
    )
    assert r.new_numbers == ()


@pytest.mark.anyio
async def test_without_a_provider_nothing_is_written() -> None:
    r = await star_complete.complete(TEXT, [Fill("S", "write")], [], guard=Guardrail(), **CTX)
    assert r.llm_unavailable and r.body is None
