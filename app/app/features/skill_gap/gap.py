"""C10 — 학습 갭 정리 (A11 매칭 결과 위의 얇은 계층, 순수 로직).

A11(`features/matching`)이 이미 공고 요건을 추출하고 자소서·경험과 대조해
`covered / in_experience_only / missing`으로 나눈다. **C10은 그 위에서 "무엇을 배워야 하나"만
골라 C14 학습 로드맵 입력으로 정리**한다 — 갭 계산을 다시 하지 않는다(중복 제거, 2026-10-22).

핵심 판단: **학습 갭 = `missing`뿐.**
- `missing`      : 자소서에도 경험에도 없음 → **배워서 채울 것**(C14가 훈련과정 매핑).
- `in_experience_only` : 경험엔 있는데 자소서에 안 씀 → **배울 게 아니라 쓸 것**(A11 hints 담당, 학습 아님).
- `covered`      : 이미 썼음 → 할 일 없음.

빈도(frequency)는 쓰지 않는다 — A11 출력에 없다(중요도 3단계로 우선순위를 가른다).
A11을 import하지 않고 **필요한 속성만 덕타이핑**으로 받는다(A11이 컬럼 바꿔도 안 깨지고 DB 없이 테스트).
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

#: A11 중요도 3단계의 우선순위(낮을수록 먼저). 학습 로드맵은 필수부터 채운다.
IMPORTANCE_RANK = {"required": 0, "preferred": 1, "mentioned": 2}

#: 학습 갭에서 기본으로 제외하는 약한 신호. `mentioned`는 공고 줄글에 스쳐 나온 말이라
#: "배워라"로 올리면 로드맵이 노이즈로 찬다. 필요하면 include_mentioned=True로 켠다.
_WEAKEST = "mentioned"


class CoverageMatch(Protocol):
    """C10이 A11 대조 결과에서 읽는 최소 모양(덕타이핑).

    A11 `features/matching.coverage.Match`가 이 모양을 만족한다
    (`m.keyword.text/.importance/.key/.fields`, `m.status`). 어댑터(`from_coverage`)가
    그 구조를 평평한 `_Match`로 바꾼다 — C10 순수 로직은 A11 타입을 몰라도 된다.
    """

    key: str
    label: str
    importance: str          # required / preferred / mentioned (A11 tier)
    status: str              # covered / in_experience_only / missing
    evidence_fields: tuple[str, ...]


@dataclass(frozen=True)
class _Match:
    """어댑터 출력 = 순수 로직 입력. A11 구조를 평평하게 편 것."""

    key: str
    label: str
    importance: str
    status: str
    evidence_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class LearningGap:
    """배워서 채워야 할 요건 1건(C14 학습 로드맵 입력)."""

    key: str
    label: str
    importance: str                  # required / preferred / mentioned
    evidence_fields: tuple[str, ...]  # 어느 공고 필드에서 나왔나 — "왜 필요한지" 근거


def from_coverage(a11_matches: Iterable[object]) -> list[_Match]:
    """A11 `coverage.Match`들을 C10 입력(`_Match`)으로 매핑하는 어댑터.

    A11을 import하지 않고 속성만 읽는다(`m.keyword.*`, `m.status`). 통합 seam은 여기 한 곳 —
    A11 구조가 바뀌면 이 함수만 고친다.
    """
    out: list[_Match] = []
    for m in a11_matches:
        kw = m.keyword  # type: ignore[attr-defined]
        out.append(
            _Match(
                key=kw.key,
                label=kw.text,
                importance=kw.importance,
                status=m.status,  # type: ignore[attr-defined]
                evidence_fields=tuple(kw.fields),
            )
        )
    return out


def learning_gaps(
    matches: Iterable[_Match],
    *,
    include_mentioned: bool = False,
) -> list[LearningGap]:
    """대조 결과에서 **배워야 할 것(`missing`)만** 골라 중요도순으로 정리한다.

    `in_experience_only`·`covered`는 학습 갭이 아니라 제외한다(위 docstring). 정렬은
    **중요도(필수→우대→언급)** → 같은 등급 내 이름순. 빈도는 쓰지 않는다(A11에 없음).
    """
    gaps = [
        m for m in matches
        if m.status == "missing" and (include_mentioned or m.importance != _WEAKEST)
    ]
    gaps.sort(key=lambda m: (IMPORTANCE_RANK.get(m.importance, 99), m.label.casefold()))
    return [
        LearningGap(m.key, m.label, m.importance, m.evidence_fields)
        for m in gaps
    ]
