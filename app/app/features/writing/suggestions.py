"""교정 제안 하나와, 수락한 것만 반영하는 함수.

★ 제안에는 원문 조각이 들어 있다. A1 의 Hit·A4 의 Finding 과 반대다.
  그 둘은 **로그로 흘러가는** 구조체라 값을 담지 않았지만, 제안은
  **작성자 본인 화면에 보여주려고** 만드는 것이라 값이 없으면 쓸모가 없다.
  대신 제안 목록은 로그에 쓰지 않는다 — 감사 로그에는 개수만 남긴다.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable, Literal, Sequence

SuggestionKind = Literal[
    "particle", "spacing", "passive", "cliche", "long_sentence", "star", "style"
]
SuggestionSource = Literal["rule", "llm"]
#: high = 규칙이 확실한 것, medium = 글쓴이가 판단해야 하는 것.
#: 한국어 조사는 정규식만으로 완전히 가릴 수 없어 medium 이다 (proofread.py 참조).
Confidence = Literal["high", "medium"]


@dataclass(frozen=True)
class Suggestion:
    """고칠 곳 하나.

    ``id`` 는 (종류·위치·원문·대안)에서 만든 해시다. 같은 글을 다시 검사하면
    같은 id 가 나와야 사용자가 "이건 거절했음"을 유지할 수 있다.
    순번을 쓰면 앞에 제안이 하나 추가될 때 뒤 번호가 전부 밀린다.
    """

    kind: SuggestionKind
    rule_id: str
    start: int
    end: int
    original: str
    suggested: str
    reason: str
    source: SuggestionSource = "rule"
    confidence: Confidence = "high"

    @property
    def id(self) -> str:
        raw = f"{self.kind}|{self.start}|{self.end}|{self.original}|{self.suggested}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]

    @property
    def is_replacement(self) -> bool:
        """글을 바꾸는 제안인가. 안내만 하는 제안(STAR 보완 등)은 False."""
        return self.suggested != "" and self.suggested != self.original


class OverlappingSuggestions(ValueError):
    """같은 자리를 고치는 제안을 동시에 수락했다."""


def apply_suggestions(text: str, suggestions: Sequence[Suggestion], accepted: Iterable[str]) -> str:
    """수락한 제안만 반영한다.

    ★ **뒤에서부터** 바꾼다. 앞에서부터 바꾸면 길이가 달라져 뒤 제안의 위치가 전부 어긋난다.

    겹치는 제안을 동시에 수락하면 예외를 낸다. 조용히 하나를 버리면 사용자는
    자기가 수락한 것이 반영됐다고 믿는다.
    """
    wanted = set(accepted)
    chosen = [s for s in suggestions if s.id in wanted and s.is_replacement]
    chosen.sort(key=lambda s: (s.start, s.end))

    for before, after in zip(chosen, chosen[1:]):
        if after.start < before.end:
            raise OverlappingSuggestions(
                f"겹치는 제안을 함께 수락했습니다: {before.rule_id}({before.start}:{before.end}) / "
                f"{after.rule_id}({after.start}:{after.end})"
            )

    out = text
    for s in reversed(chosen):
        out = out[: s.start] + s.suggested + out[s.end :]
    return out
