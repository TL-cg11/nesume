"""A13 — 글자 수 세기. **B4 와 같은 기준이어야 한다.**

## 왜 세는 방법부터 맞추는가

자소서는 "1,000자 이내" 같은 제한이 붙는다. A13 이 "맞습니다" 라고 한 글이 저장할 때
제한을 넘으면 **사용자는 A13 을 믿지 않게 된다.** 그래서 기준을 B 쪽에 맞췄다.

    # app/app/features/resumes/service.py (B 소유)
    # 글자 수는 사용자가 입력한 원문 기준(공백 포함)
    char_count=len(body)

즉 **`len(원문)` — 공백·줄바꿈 포함**이다. 공백을 뺀 수는 참고로만 함께 돌려준다.

★ **토큰화된 본문을 세면 틀어진다.** 저장된 `versions.body` 는 PII 토큰화 상태다
  (``[[PHONE_1]]`` 13자 ≠ ``010-1234-5678`` 13자… 값마다 길이가 다르다).
  B 도 `char_count` 는 **토큰화 전 원문**으로 센다. A13 은 **사용자가 보는 글**을 센다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: B 가 `char_count` 를 세는 방식. 바꾸려면 B4 와 함께 바꿔야 한다.
COUNT_BASIS = "len(원문), 공백·줄바꿈 포함"

#: PII 토큰 모양. 세기 전에 이게 남아 있으면 원문이 아니다.
_TOKEN = re.compile(r"\[\[[A-Z_]+_\d+\]\]")

_WHITESPACE = re.compile(r"\s")


class TokenizedTextError(ValueError):
    """토큰화된 본문을 세려고 했다.

    조용히 세면 **저장될 글자 수와 다른 수**를 사용자에게 보여준다. 터뜨리는 쪽이 낫다.
    """


@dataclass(frozen=True)
class CharCount:
    #: B4 기준 — 이 값이 `versions.char_count` 가 된다
    total: int
    #: 참고용. 공백을 빼고 센 수 (기관마다 이 기준을 쓰는 곳이 있다)
    without_spaces: int

    def over_by(self, limit: int | None) -> int:
        """제한을 몇 자 넘었나. 제한이 없거나 넘지 않았으면 0."""
        if limit is None:
            return 0
        return max(0, self.total - limit)

    def fits(self, limit: int | None) -> bool:
        return self.over_by(limit) == 0


def count(text: str, *, allow_tokens: bool = False) -> CharCount:
    """글자 수를 센다. 기준은 `COUNT_BASIS`.

    ``allow_tokens`` 를 주지 않으면 PII 토큰이 섞인 글을 거절한다.
    """
    if not allow_tokens and _TOKEN.search(text):
        raise TokenizedTextError(
            "PII 토큰이 섞여 있습니다. 글자 수는 사용자가 보는 원문으로 세야 합니다 "
            "(저장된 본문은 토큰화 상태입니다)"
        )
    return CharCount(total=len(text), without_spaces=len(_WHITESPACE.sub("", text)))
