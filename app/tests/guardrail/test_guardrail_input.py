"""A7·A11·A13 이 가드레일에 **무엇을 넘기는가**.

조립한 프롬프트를 넘기면 A3·A12 가 우리 템플릿까지 검사 대상으로 본다. 그러면
문장 전체를 보는 규칙이 죽는다 — A12 `is_continuation` 은 ``^...$`` 앵커라
템플릿에 싸이면 영원히 안 맞고, 그 때문에 `A10-MULTI-04` 가 B16 1차 측정에서
통과하지 못했다.

**이 파일이 그 회귀를 막는다.** 네 기능이 같은 규약을 지키는지 한자리에서 본다.
"""

from __future__ import annotations

import pytest

from app.features.matching import service as matching
from app.features.matching.coverage import ExperienceRef, UserEvidence
from app.features.matching.keywords import PostingFields
from app.features.style import service as style
from app.features.writing import service as writing
from app.guardrail import Guardrail, LlmClient
from app.guardrail.multiturn import is_continuation
from app.pii import InMemoryVaultStore
from tests.guardrail.fakes import FakeProvider


class Spy(Guardrail):
    """`_before_llm` 에 들어온 질의를 적어 둔다 — 검사 대상이 무엇이었는지 본다."""

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        object.__setattr__(self, "seen", [])

    async def _before_llm(self, query, ctx):
        self.seen.append(query)
        return await super()._before_llm(query, ctx)


def _spy(reply: str = "응답입니다") -> tuple[Spy, FakeProvider]:
    provider = FakeProvider(reply=reply)
    return Spy(llm=LlmClient(provider=provider), vault=InMemoryVaultStore()), provider


CTX = dict(user_id="u1", role="user", session_id="s1")
TURN = "그다음은?"


@pytest.mark.anyio
async def test_a7_passes_the_user_text() -> None:
    guard, provider = _spy()
    await writing.improve(TURN, guard=guard, **CTX)

    assert guard.seen == [TURN], "검사 대상은 사용자가 쓴 글 그대로여야 한다"
    assert TURN in provider.calls[0].prompt, "템플릿 조립은 A8 안에서 일어난다"
    assert provider.calls[0].prompt != TURN, "조립은 분명히 일어나야 한다"


@pytest.mark.anyio
async def test_a13_passes_the_user_text() -> None:
    # 제한을 넘겨야 다시 쓴다. 넉넉한 제한이면 모델을 아예 부르지 않는다
    long_text = "개인적으로 협업을 하게 되었다고 생각합니다. " * 4
    guard, provider = _spy()
    await style.adjust(long_text, limit=20, guard=guard, **CTX)

    assert provider.calls, "제한을 넘겼으니 모델을 불러야 한다"
    (checked,) = set(guard.seen)
    assert checked != provider.calls[0].prompt, "조립은 A8 안에서 일어난다"
    assert checked in provider.calls[0].prompt, "검사한 글이 프롬프트에 그대로 들어간다"
    assert "자기소개서" not in checked, "템플릿 문구가 검사 대상에 섞이면 안 된다"


@pytest.mark.anyio
@pytest.mark.parametrize("query", ["그다음은?", "계속 알려줘", "이어서 해 주세요"])
async def test_the_checked_query_is_short_enough_for_anchored_rules(query) -> None:
    """★ 이것이 요점이다.

    A12 `is_continuation` 은 문장 **전체**가 이어묻기인지 본다. 조립한 프롬프트를
    넘기면 이 판정이 영원히 False 가 된다.
    """
    guard, _ = _spy()
    await writing.improve(query, guard=guard, **CTX)

    (checked,) = guard.seen
    assert is_continuation(checked), "가드레일이 본 글에서 이어묻기 판정이 서야 한다"


@pytest.mark.anyio
async def test_a11_passes_every_non_template_part() -> None:
    """경험만 넘기면 빠진 낱말이 **검사와 치환에서 빠진다.** 둘 다 넘겨야 한다."""
    guard, provider = _spy("키워드|||문장입니다")
    posting = PostingFields(job_content="파이썬 경험자를 찾습니다")
    evidence = UserEvidence(
        resume_text="",
        experiences=(ExperienceRef(label="프로젝트", text="파이썬으로 만들었습니다"),),
    )
    await matching.analyze(posting, evidence, guard=guard, **CTX)

    # 건너뛰지 않고 단언한다 — 모델을 안 부르게 바뀌면 이 시험이 **조용히 빈 시험**이 된다
    assert provider.calls, "경험에만 있는 요건이 있으므로 모델을 불러야 한다"
    (checked,) = guard.seen
    assert "파이썬으로 만들었습니다" in checked, "경험 글이 검사 대상에 있어야 한다"
    assert "파이썬" in checked, "빠진 낱말도 검사 대상에 있어야 한다"
    assert matching._PROMPT[:20] not in checked, "템플릿은 검사 대상이 아니다"


@pytest.mark.anyio
async def test_a11_splits_the_parts_back_for_the_prompt() -> None:
    """이어 보낸 두 덩어리가 프롬프트에서는 제자리로 돌아가야 한다."""
    guard, provider = _spy("키워드|||문장입니다")
    posting = PostingFields(job_content="파이썬 경험자를 찾습니다")
    evidence = UserEvidence(
        resume_text="",
        experiences=(ExperienceRef(label="프로젝트", text="파이썬으로 만들었습니다"),),
    )
    await matching.analyze(posting, evidence, guard=guard, **CTX)

    assert provider.calls, "경험에만 있는 요건이 있으므로 모델을 불러야 한다"
    prompt = provider.calls[0].prompt
    assert matching._GUARD_SEP not in prompt, "표시는 모델에 가면 안 된다"
    assert "--- 경험 ---" in prompt and "빠진 낱말" in prompt
