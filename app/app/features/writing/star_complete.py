"""A7 — STAR 보완. 빠지거나 약한 요소를 **사용자가 허락한 것만** 모델이 써 넣는다.

## ★ 이전 결정과의 관계

2026-10-22 팀 회의와 `star_review` 는 "빈 요소를 모델이 채우면 없는 경험을 지어낸다" 고
보고 질문만 돌려줬다. 2026-10-29 요청으로 **사용자가 요소마다 고르는** 보완을 더한다.

    write    없는 요소를 모델이 지어서 써 넣는다 (사용자가 팝업에서 허락한 경우만)
    improve  있지만 약한 요소를 더 구체적으로 다듬는다
    omit     그 요소는 넣지 않는다 — 모델에게 "새로 만들지 말라" 고 적는다

지어낸 내용이 사실처럼 저장되는 것이 위험의 전부라, 아래 두 겹으로 드러낸다.

  - 바뀐 곳은 **서버가 원문과 비교해** 표시한다(B4 `diff_segments`). 모델이 스스로
    표시하게 하면 표시를 빠뜨린 문장은 원문처럼 보인다.
  - 원문·힌트에 없던 숫자는 `new_numbers` 로 따로 돌려준다. 자소서에서 가장 위험한
    지어낸 사실이 성과 수치다 (A13 `invented_numbers` 와 같은 판단).

힌트(사용자가 적은 실제 사실)가 있으면 그것만 쓰게 한다 — 지어내지 않고 채우는 길이다.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal

from app.features.resumes import service as resumes_service
from app.features.style.service import clean_reply, invented_numbers
from app.features.writing.star import STAR_ELEMENTS, StarElement
from app.guardrail import Guardrail, LlmUnavailable, RequestContext

FEATURE = "writing.star_complete"

#: 요소별 힌트 길이. 문장 몇 개면 충분하다 — 길면 본문을 통째로 넣는 길이 된다
MAX_HINT_LEN = 300

Mode = Literal["write", "improve"]

_LABEL: dict[StarElement, str] = {
    "S": "상황 — 언제·어디서·어떤 배경이었는가",
    "T": "과제 — 무엇을 해야 했는가 (목표·맡은 역할)",
    "A": "행동 — 글쓴이 본인이 구체적으로 무엇을 했는가",
    "R": "결과 — 어떻게 되었는가 (변화·성과)",
}


class StarCompleteError(ValueError):
    """요청이 규약에 맞지 않는다. 라우터가 400 으로 바꾼다."""


@dataclass(frozen=True)
class Fill:
    element: StarElement
    mode: Mode
    hint: str = ""


@dataclass(frozen=True)
class StarCompletion:
    body: str | None = None
    segments: list[dict] = field(default_factory=list)
    #: 원문·힌트에 없던 숫자. 화면이 "실제와 맞는지 확인" 으로 짚는다
    new_numbers: tuple[str, ...] = ()
    llm_used: bool = False
    llm_unavailable: bool = False
    blocked_reason: str | None = None
    notices: tuple[str, ...] = ()


def validate(fills: list[Fill], omit: list[str]) -> None:
    if not fills:
        raise StarCompleteError("보완할 요소를 하나 이상 골라야 합니다")
    seen = [f.element for f in fills] + list(omit)
    if any(e not in STAR_ELEMENTS for e in seen):
        raise StarCompleteError(f"요소는 {STAR_ELEMENTS} 중 하나여야 합니다")
    if len(seen) != len(set(seen)):
        raise StarCompleteError("같은 요소를 두 번 고를 수 없습니다")
    for f in fills:
        if f.mode not in ("write", "improve"):
            raise StarCompleteError(f"보완 방식이 올바르지 않습니다: {f.mode!r}")
        if len(f.hint) > MAX_HINT_LEN:
            raise StarCompleteError(f"참고 사실은 {MAX_HINT_LEN}자까지입니다")


def build_prompt(text: str, fills: list[Fill], omit: list[str]) -> str:
    todo: list[str] = []
    for f in fills:
        what = (
            "글에 없습니다. 새로 써 넣습니다." if f.mode == "write"
            else "있지만 모호합니다. 더 구체적으로 다듬습니다."
        )
        line = f"- {_LABEL[f.element]}: {what}"
        if f.hint.strip():
            line += f"\n  글쓴이가 알려 준 실제 사실(이것만 씁니다): {f.hint.strip()}"
        todo.append(line)
    skip = [f"- {_LABEL[e]}: 글쓴이가 넣지 않기로 했습니다. **새로 만들지 않습니다.**" for e in omit]

    return (
        "다음 자기소개서 글을 STAR 구성(상황·과제·행동·결과)에 맞게 보완해 주십시오.\n\n"
        "할 일:\n" + "\n".join(todo) + "\n\n"
        + ("넣지 않을 것:\n" + "\n".join(skip) + "\n\n" if skip else "")
        + "규칙:\n"
        "- 위 '할 일' 에 적은 요소만 쓰거나 다듬습니다. 나머지 원문 문장은 그대로 둡니다.\n"
        "- 실제 사실이 주어진 요소는 그 사실만 씁니다. 주어지지 않았으면 글의 맥락에 맞게 "
        "자연스럽게 쓰되, 확인할 수 없는 구체적인 숫자는 가급적 쓰지 않습니다.\n"
        "- 문체(문장 끝맺음)는 원문과 같게 씁니다.\n"
        "- 보완한 글 전체만 씁니다. 설명·머리말·따옴표를 붙이지 않습니다.\n\n"
        f"--- 글 ---\n{text}"
    )


async def complete(
    text: str,
    fills: list[Fill],
    omit: list[str],
    *,
    guard: Guardrail,
    user_id: str,
    role: str,
    session_id: str = "",
    is_test: bool = False,
    request_id: uuid.UUID | None = None,
) -> StarCompletion:
    """고른 요소를 보완한 글을 만든다. **저장하지 않는다.** 사용자가 보고 고른다."""
    validate(fills, omit)

    ctx = RequestContext(
        user_id=user_id, role=role, feature=FEATURE,
        session_id=session_id, is_test=is_test,
        request_id=request_id or uuid.uuid4(),
    )
    try:
        # 힌트도 프롬프트 안에 있어 본문과 함께 치환된다 (A1)
        result = await guard.run(build_prompt(text, fills, omit), ctx)
    except LlmUnavailable:
        return StarCompletion(llm_unavailable=True)

    if result.blocked:
        return StarCompletion(llm_used=True, blocked_reason=result.verdict.rule_id or "차단되었습니다")

    body = clean_reply(result.text)
    if not body:
        return StarCompletion(
            llm_used=True,
            notices=("AI가 글을 돌려주지 않았습니다. 다시 시도해 주십시오.",),
        )

    hints = " ".join(f.hint for f in fills)
    return StarCompletion(
        body=body,
        segments=resumes_service.diff_segments(text, body),
        new_numbers=tuple(sorted(invented_numbers(f"{text} {hints}", body))),
        llm_used=True,
    )


__all__ = ["FEATURE", "Fill", "MAX_HINT_LEN", "StarCompleteError", "StarCompletion", "complete"]
