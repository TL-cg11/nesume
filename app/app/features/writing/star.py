"""A7 — STAR 요소 분석.

STAR 는 경험을 쓰는 네 토막이다.

    S  Situation  어떤 상황이었나 (배경·시점)
    T  Task       무엇을 해야 했나 (목표·역할)
    A  Action     무엇을 했나 (구체적 행동)
    R  Result     어떻게 됐나 (결과·수치)

자소서에서 가장 흔한 문제는 A 만 잔뜩 쓰고 T 와 R 이 없는 것이다.
"무엇을 했다"는 많은데 "왜 했고 어떻게 됐는지"가 없으면 평가자가 판단할 근거가 없다.

★ tasks.md 의 **"STAR 요소 2개 이하면 보완 안내"** 를 그대로 따른다.
  요소가 둘 이하인 글을 LLM 으로 변환하면 **없는 내용을 지어내게** 된다.
  모델은 빈칸을 그럴듯하게 채우지, 사실을 묻지 않는다. 그래서 변환 대신
  "무엇이 빠졌는지" 를 알려주고 글쓴이가 채우게 한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.features.writing.suggestions import Suggestion

StarElement = Literal["S", "T", "A", "R"]
STAR_ELEMENTS: tuple[StarElement, ...] = ("S", "T", "A", "R")

ELEMENT_NAMES: dict[StarElement, str] = {
    "S": "상황(Situation)",
    "T": "과제(Task)",
    "A": "행동(Action)",
    "R": "결과(Result)",
}

#: 요소별 단서. 오탐보다 미탐이 안전한 쪽으로 좁게 잡았다 —
#: 있는데 없다고 하면 글쓴이가 한 번 더 보면 그만이지만,
#: 없는데 있다고 하면 빠진 채로 제출된다.
_CLUES: dict[StarElement, tuple[re.Pattern[str], ...]] = {
    "S": (
        re.compile(r"\d{4}\s*년|\d+\s*(학년|학기|개월|년간)"),
        re.compile(r"(당시|시절|무렵|프로젝트에서|인턴|동아리|학회|수업에서|현장에서)"),
    ),
    "T": (
        re.compile(r"(목표|과제|미션|요구사항|해결해야|필요했|맡게\s*되|담당하게)"),
        re.compile(r"(역할|책임)(을|이|은)"),
    ),
    "A": (
        re.compile(r"(구현|설계|분석|제안|개선|도입|구축|작성|조율|설득|주도|리팩터|자동화)(했|하였|한)"),
        re.compile(r"(직접|스스로|먼저)\s*\S*(했|하였)"),
    ),
    "R": (
        re.compile(r"\d+\s*(%|퍼센트|배|초|분|시간|일|건|명|원|만원)"),
        re.compile(r"(향상|단축|절감|증가|감소|달성|개선)(했|되었|시켰|하였)"),
        re.compile(r"(수상|선정|채택|합격|출시|배포)(했|되었|하였)"),
    ),
}


@dataclass(frozen=True)
class StarAnalysis:
    present: frozenset[StarElement]
    #: 요소별로 근거가 된 위치 (화면에서 하이라이트에 쓴다)
    evidence: dict[StarElement, tuple[int, int]]

    @property
    def missing(self) -> tuple[StarElement, ...]:
        return tuple(e for e in STAR_ELEMENTS if e not in self.present)

    @property
    def count(self) -> int:
        return len(self.present)

def analyze(text: str) -> StarAnalysis:
    """어떤 요소가 들어 있는지 본다. 글을 바꾸지 않는다."""
    present: set[StarElement] = set()
    evidence: dict[StarElement, tuple[int, int]] = {}

    if not text or not text.strip():
        return StarAnalysis(present=frozenset(), evidence={})

    for element, patterns in _CLUES.items():
        for pattern in patterns:
            m = pattern.search(text)
            if m:
                present.add(element)
                evidence[element] = (m.start(), m.end())
                break

    return StarAnalysis(present=frozenset(present), evidence=evidence)


#: 요소별 보완 질문. 지시가 아니라 **질문**으로 적는다 —
#: 글쓴이가 답을 떠올려야 사실이 들어간다.
_GUIDE: dict[StarElement, str] = {
    "S": "언제, 어디서 있었던 일인지 한 줄로 적어 보십시오. (예: 2025년 교내 프로젝트에서)",
    "T": "그때 무엇을 해야 했습니까? 목표나 맡은 역할을 적어 보십시오.",
    "A": "그래서 무엇을 했습니까? 가장 결정적이었던 행동 하나를 구체적으로 적어 보십시오.",
    "R": "결과가 어떻게 됐습니까? 가능하면 숫자로 적어 보십시오. (예: 응답시간 40% 단축)",
}


#: 다른 모듈(star_review)이 쓰는 이름. 질문 문구는 한 곳에만 둔다
QUESTIONS = _GUIDE


def guidance(analysis: StarAnalysis, text: str) -> list[Suggestion]:
    """빠진 요소에 대한 보완 안내를 만든다.

    글을 바꾸는 제안이 아니라 **안내**다. 그래서 ``suggested`` 가 비어 있다 —
    무엇을 쓸지는 글쓴이만 안다.
    """
    out: list[Suggestion] = []
    end = len(text)
    for element in analysis.missing:
        out.append(Suggestion(
            kind="star", rule_id=f"WR_STAR_{element}",
            start=end, end=end,       # 글 전체에 대한 안내라 끝에 붙인다
            original="", suggested="",
            reason=f"{ELEMENT_NAMES[element]}가 보이지 않습니다. {_GUIDE[element]}",
        ))
    return out
