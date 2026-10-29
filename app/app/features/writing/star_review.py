"""A7 — STAR 판정을 모델에게 맡긴다. 규칙(`star.analyze`)은 모델을 못 쓸 때의 대비다.

## ★ 왜 규칙만으로는 안 되는가

`star.analyze` 는 단서 낱말로 찾는다. "도입했" 은 행동(A)으로 잡지만
"도입하는 것을 통해 해결하였습니다" 는 놓친다. 반대로 "목표" 라는 낱말만 있으면
과제(T)가 있다고 본다. 그리고 **있다/없다만** 말할 수 있다 — 자소서에서 정작
중요한 "결과는 있는데 숫자가 없다", "행동이 팀 단위라 본인 몫이 안 보인다" 는
뜻을 읽어야 알 수 있다.

## ★ 모델에게 시키는 것과 시키지 않는 것

    시킨다     요소별 판정(충분·부족·없음), 근거 조각, 부족한 점 한 문장
    안 시킨다  고쳐 쓴 문장, 채워 넣을 내용

없는 요소를 모델이 채우면 **없는 경험을 지어낸다** (A7 star.py·2026-10-22 회의와 같은
판단). 그래서 보완은 `star.QUESTIONS` 의 **질문**으로만 하고, 모델의 말은 "무엇이
부족한지" 에서 멈춘다.

★ 근거 조각은 **원문과 대조해** 글에 있는 것만 남긴다 (`service.parse_llm_suggestions`
  와 같은 방어). 모델이 글에 없는 문장을 근거로 대면 그 판정은 믿을 수 없다.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Literal

from app.features.writing import star
from app.features.writing.star import ELEMENT_NAMES, STAR_ELEMENTS, StarElement
from app.guardrail import Guardrail, LlmUnavailable, RequestContext

FEATURE = "writing.star"

SEP = "|||"

Status = Literal["ok", "weak", "missing"]

_STATUS: dict[str, Status] = {"충분": "ok", "부족": "weak", "없음": "missing"}

_PROMPT = """다음 자기소개서 글에서 STAR 네 요소가 각각 얼마나 드러나는지 판정해 주십시오.

S 상황: 언제·어디서·어떤 배경이었는가
T 과제: 무엇을 해야 했는가 (목표·맡은 역할)
A 행동: 글쓴이 **본인이** 구체적으로 무엇을 했는가
R 결과: 어떻게 되었는가 (가능하면 수치나 변화)

판정은 셋 중 하나입니다.
- 충분: 분명히 드러난다
- 부족: 있긴 하지만 모호하다 (예: 결과에 수치·변화가 없다, 행동이 팀 단위라 본인 몫이 안 보인다)
- 없음: 보이지 않는다

규칙:
- 글에 없는 내용을 지어내지 않습니다. 고쳐 쓴 문장이나 채울 내용을 제안하지 않습니다.
- 근거는 아래 글에서 **글자 그대로 옮긴 한 문장**만 씁니다. 바꿔 쓰지 않습니다. 없음이면 비웁니다.
- 충분이면 마지막 칸을 비웁니다.
- S, T, A, R 순서로 정확히 4줄만 씁니다. 줄마다 칸은 {sep} 로 나눕니다. 다른 설명은 쓰지 않습니다.

칸 순서: 요소{sep}판정{sep}근거 문장{sep}부족한 점
예시 (다른 글의 예입니다):
R{sep}부족{sep}그 결과 매출이 늘었습니다.{sep}얼마나 늘었는지 수치나 변화가 없습니다.
S{sep}충분{sep}작년 여름 물류센터에서 일했습니다.{sep}

--- 글 ---
{text}"""


@dataclass(frozen=True)
class ElementReview:
    element: StarElement
    status: Status
    #: 글에 실제로 있는 근거 조각. 없거나 원문과 맞지 않으면 None
    quote: str | None = None
    #: 무엇이 부족한지 (모델). 충분이면 비운다
    comment: str | None = None
    #: 판정 출처. 모델 응답에서 이 요소를 못 읽으면 규칙으로 채운다
    source: Literal["llm", "rule"] = "llm"

    @property
    def question(self) -> str | None:
        """보완 질문. 충분하면 묻지 않는다."""
        return None if self.status == "ok" else star.QUESTIONS[self.element]


@dataclass(frozen=True)
class StarReview:
    elements: tuple[ElementReview, ...]
    llm_used: bool = False
    llm_unavailable: bool = False
    blocked_reason: str | None = None


def rule_review(text: str) -> tuple[ElementReview, ...]:
    """모델 없이 규칙으로. 있다/없다만 말할 수 있다."""
    analysis = star.analyze(text)
    out: list[ElementReview] = []
    for e in STAR_ELEMENTS:
        span = analysis.evidence.get(e)
        out.append(ElementReview(
            element=e,
            status="ok" if e in analysis.present else "missing",
            quote=text[span[0]:span[1]] if span else None,
            source="rule",
        ))
    return tuple(out)


#: 모델이 형식 안내의 칸 이름을 값 앞에 그대로 붙여 오는 일이 잦다(실모델 확인).
#: "근거 문장 그 결과…" 를 그대로 대조하면 글에 없는 근거가 되어 버려진다
_LABEL = re.compile(r"^\s*(근거\s*(조각|문장)?|부족한\s*점(\s*한\s*문장)?|판정)\s*[:：]?\s*")


def _cell(value: str) -> str:
    return _LABEL.sub("", value).strip().strip("\"'“”‘’ ")


def parse_reply(reply: str, text: str) -> tuple[ElementReview, ...]:
    """모델 응답을 요소별 판정으로. 읽지 못한 요소는 규칙 판정으로 채운다."""
    found: dict[StarElement, ElementReview] = {}
    for line in reply.splitlines():
        parts = [p.strip() for p in line.strip().split(SEP)]
        if len(parts) < 2:
            continue
        key = parts[0].strip("*- ").upper()[:1]
        status = _STATUS.get(_cell(parts[1]).strip("*"))
        if key not in STAR_ELEMENTS or status is None or key in found:
            continue
        quote = _cell(parts[2]) if len(parts) > 2 else ""
        # ★ 글에 없는 근거는 버린다
        quote_ok = bool(quote) and quote in text
        comment = _cell(parts[3]) if len(parts) > 3 else ""
        comment = comment or None
        found[key] = ElementReview(  # type: ignore[index]
            element=key,  # type: ignore[arg-type]
            status=status,
            quote=quote if quote_ok else None,
            comment=None if status == "ok" else comment,
        )

    fallback = {r.element: r for r in rule_review(text)}
    return tuple(found.get(e, fallback[e]) for e in STAR_ELEMENTS)


async def review(
    text: str,
    *,
    guard: Guardrail,
    user_id: str,
    role: str,
    session_id: str = "",
    is_test: bool = False,
    request_id: uuid.UUID | None = None,
) -> StarReview:
    ctx = RequestContext(
        user_id=user_id, role=role, feature=FEATURE,
        session_id=session_id, is_test=is_test,
        request_id=request_id or uuid.uuid4(),
    )
    try:
        result = await guard.run(_PROMPT.format(sep=SEP, text=text), ctx)
    except LlmUnavailable:
        return StarReview(elements=rule_review(text), llm_unavailable=True)

    if result.blocked:
        return StarReview(
            elements=rule_review(text), llm_used=True,
            blocked_reason=result.verdict.rule_id or "차단되었습니다",
        )
    return StarReview(elements=parse_reply(result.text, text), llm_used=True)


__all__ = ["ELEMENT_NAMES", "ElementReview", "FEATURE", "StarReview", "parse_reply", "review", "rule_review"]
