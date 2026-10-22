"""A13 — 글자 수를 줄이는 **규칙** 제안.

모델을 부르기 전에 규칙으로 줄일 수 있는 만큼 줄인다. 이유는 A7·A11 과 같다 —
값이 들지 않고, 같은 글에 항상 같은 결과가 나오고, 근거(규칙 ID)를 댈 수 있다.

## 규칙은 "사실을 지우지 않는 것" 만 넣는다

줄이기는 **본문을 삭제하는 일**이라 환각보다 위험하다. 모델이 지어내는 것은 검증으로
걸러낼 수 있지만, 규칙이 지운 문장은 **사용자가 알아채지 못하면 그대로 제출된다.**
그래서 넣은 것은 세 종류뿐이다.

| 종류 | 예 | 잃는 것 |
| --- | --- | --- |
| 공백·줄바꿈 정리 | ``"했고   그래서"`` → ``"했고 그래서"`` | **없음** (무손실) |
| 늘어진 표현 축약 | ``"하게 되었습니다"`` → ``"했습니다"`` | 없음 |
| 군더더기 부사 | ``"매우 많은"`` → ``"많은"`` | 어감 (그래서 수락을 사용자에게 맡긴다) |

**문장·절을 통째로 지우는 규칙은 넣지 않았다.** 무엇이 덜 중요한지는 글쓴이만 안다.
규칙으로 모자라면 모델에게 **다시 쓰게** 하고 그 결과를 검증한다 (`service.py`).

## 적용은 뒤에서 앞으로

앞에서부터 바꾸면 뒤 제안의 위치가 전부 밀린다 (A7 에서 같은 실수를 했다).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Literal

Confidence = Literal["high", "medium"]

#: 규칙 ID 접두어. A7 은 ``WR_``, A13 은 ``ST_`` — 감사·집계에서 구분된다.
RULE_PREFIX = "ST_"


class StaleTrim(ValueError):
    """제안을 받은 뒤 글이 바뀌었다. 그대로 적용하면 엉뚱한 자리가 지워진다."""


class OverlappingTrims(ValueError):
    """겹치는 제안을 동시에 수락했다. 하나를 조용히 버리면 반영된 줄 안다."""


@dataclass(frozen=True)
class Trim:
    rule_id: str
    start: int
    end: int
    original: str
    replacement: str
    reason: str
    confidence: Confidence = "high"

    @property
    def saved(self) -> int:
        return len(self.original) - len(self.replacement)

    @property
    def id(self) -> str:
        """내용 해시. 글이 바뀌면 같은 자리라도 다른 id 가 된다 (A7 과 같은 방식)."""
        raw = f"{self.rule_id}|{self.start}|{self.end}|{self.original}|{self.replacement}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


#: (규칙 ID, 정규식, 치환, 이유, 신뢰도)
#: ★ 정규식은 **줄이기만** 한다. 치환 결과가 원문보다 길면 `_RULES` 검사에서 걸린다.
_RULES: tuple[tuple[str, re.Pattern[str], str, str, Confidence], ...] = (
    (
        "ST_SPACE",
        re.compile(r"[ \t ]{2,}"),
        " ",
        "연속된 공백을 하나로 줄였습니다",
        "high",
    ),
    (
        "ST_BLANKLINE",
        re.compile(r"\n{3,}"),
        "\n\n",
        "빈 줄이 겹쳐 있습니다",
        "high",
    ),
    (
        "ST_VERBOSE",
        re.compile(r"하게\s*되었습니다"),
        "했습니다",
        "'하게 되었습니다'는 '했습니다'로 줄일 수 있습니다",
        "high",
    ),
    (
        "ST_VERBOSE",
        re.compile(r"에\s*대하여"),
        "에 대해",
        "'에 대하여'는 '에 대해'로 줄일 수 있습니다",
        "high",
    ),
    (
        "ST_VERBOSE",
        re.compile(r"[를을]\s*통하여"),
        "를 통해",
        "'통하여'는 '통해'로 줄일 수 있습니다",
        "high",
    ),
    (
        "ST_VERBOSE",
        re.compile(r"그렇기\s*때문에"),
        "그래서",
        "'그렇기 때문에'는 '그래서'로 줄일 수 있습니다",
        "high",
    ),
    (
        "ST_VERBOSE",
        re.compile(r"하였습니다"),
        "했습니다",
        "'하였습니다'는 '했습니다'로 줄일 수 있습니다",
        "high",
    ),
    (
        "ST_FILLER",
        # 뒤에 꾸밀 말이 있어야 부사다. 문장 끝의 "정말." 같은 것은 건드리지 않는다
        re.compile(r"(매우|정말|너무|굉장히|상당히|무척|엄청)\s+(?=\S)"),
        "",
        "어감만 더하는 부사입니다. 지우면 글자 수가 줄어듭니다",
        "medium",
    ),
    (
        "ST_FILLER",
        # ★ 앞의 "저는" 까지 지우지 않는다. 주어를 말없이 없애면 글쓴이가 알아채기 어렵다
        re.compile(r"개인적으로\s+(?=\S)"),
        "",
        "'개인적으로'는 거의 뜻을 더하지 않습니다",
        "medium",
    ),
    (
        # ★ "이" 를 함께 먹어야 한다. "강점이라고 생각합니다" 를 "입니다" 로만 바꾸면
        #   "강점이입니다" 가 된다 (실제로 그렇게 났다). 받침 있는 말 뒤의 "이라고" 다.
        "ST_HEDGE",
        re.compile(r"이라고\s*생각합니다"),
        "입니다",
        "'~이라고 생각합니다'를 단정하면 짧아지고 자신 있게 읽힙니다",
        "medium",
    ),
    (
        # 위에서 "이라고" 를 먼저 집으므로 여기 오는 것은 "~다고/~라고" 뿐이다
        "ST_HEDGE",
        re.compile(r"(?<!이)라고\s*생각합니다"),
        "라고 봅니다",
        "'생각합니다'를 '봅니다'로 줄일 수 있습니다",
        "medium",
    ),
)


def find_trims(text: str) -> list[Trim]:
    """줄일 수 있는 자리를 모두 찾는다. 겹치는 자리는 **앞선 규칙**이 이긴다.

    규칙 순서가 곧 우선순위다 — 무손실 규칙(공백)을 앞에 두었다.
    """
    out: list[Trim] = []
    taken: list[tuple[int, int]] = []

    for rule_id, pattern, replacement, reason, confidence in _RULES:
        for m in pattern.finditer(text):
            start, end = m.start(), m.end()
            if any(start < t_end and t_start < end for t_start, t_end in taken):
                continue
            original = m.group()
            if len(replacement) >= len(original):
                continue  # 줄지 않는다. 길이 조정 기능이 글을 늘리면 안 된다
            out.append(Trim(
                rule_id=rule_id, start=start, end=end,
                original=original, replacement=replacement,
                reason=reason, confidence=confidence,
            ))
            taken.append((start, end))

    out.sort(key=lambda t: (t.start, t.end, t.rule_id))
    return out


def savings(trims: list[Trim] | tuple[Trim, ...]) -> int:
    """제안을 모두 수락하면 줄어드는 글자 수."""
    return sum(t.saved for t in trims)


def apply_trims(text: str, trims: list[Trim] | tuple[Trim, ...], accepted: set[str]) -> str:
    """수락한 제안만 반영한다. **뒤에서 앞으로** 적용한다.

    - 자리의 원문이 다르면 `StaleTrim` — 받은 뒤 글을 고쳤다는 뜻이다
    - 겹치는 둘을 동시에 수락하면 `OverlappingTrims`
    """
    chosen = [t for t in trims if t.id in accepted]
    chosen.sort(key=lambda t: t.start)

    for prev, nxt in zip(chosen, chosen[1:], strict=False):
        if nxt.start < prev.end:
            raise OverlappingTrims(
                f"겹치는 제안을 동시에 수락했습니다: {prev.rule_id} · {nxt.rule_id}"
            )

    out = text
    for trim in reversed(chosen):
        if out[trim.start : trim.end] != trim.original:
            raise StaleTrim(
                f"글이 바뀌어 제안을 반영할 수 없습니다 ({trim.rule_id}). 다시 검사해 주십시오"
            )
        out = out[: trim.start] + trim.replacement + out[trim.end :]
    return out
