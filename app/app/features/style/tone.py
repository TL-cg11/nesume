"""A13 — 문체 판정과 **혼용 탐지**.

자소서에서 흔한 사고는 틀린 문장이 아니라 **섞인 문체**다.

    "저는 책임감이 강합니다. 그래서 끝까지 해냈어요."
                     ^^^^ 합니다체          ^^^^ 해요체

읽는 사람에게는 **급하게 이어 붙인 글**로 보인다. 맞춤법 검사(A7)는 둘 다 맞다고 하므로
잡히지 않는다 — 그래서 A13 이 따로 본다.

## 네 가지로 본다

| 문체 | 예 | 자소서에서 |
| --- | --- | --- |
| `formal` 합니다체 | 했습니다 · 입니다 | **표준** |
| `polite` 해요체 | 했어요 · 이에요 | 지원서에는 쓰지 않는다 |
| `plain` 했다체 | 했다 · 이다 | 보고서체. 섞이면 튄다 |
| `nominal` 음슴체 | 했음 · 담당함 | 이력서 항목에는 쓰지만 문항 답변에는 안 쓴다 |

★ **판정 순서가 중요하다.** `입니다` 는 `다` 로 끝나므로 `plain` 규칙이 먼저 보면
  합니다체 문장이 전부 했다체로 잡힌다. A1·A3 에서 반복됐던 **규칙 우선순위** 문제다.
  그래서 `formal` → `polite` → `nominal` → `plain` 순으로 본다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Tone = Literal["formal", "polite", "plain", "nominal"]
TONES: tuple[Tone, ...] = ("formal", "polite", "plain", "nominal")

TONE_NAMES: dict[Tone, str] = {
    "formal": "합니다체",
    "polite": "해요체",
    "plain": "했다체",
    "nominal": "음슴체",
}

#: 자소서 문항 답변의 표준 문체.
DEFAULT_TONE: Tone = "formal"

#: 문장 끝에서 보는 어미. **순서가 판정 우선순위다** (모듈 주석 ★ 참조).
_ENDINGS: tuple[tuple[Tone, re.Pattern[str]], ...] = (
    # 합니다체 — 'ㅂ니다/습니다' 를 '다' 보다 먼저 본다
    ("formal", re.compile(r"(습니다|습니까|ㅂ니다|입니다|니다|니까)$")),
    # 해요체 — '요' 로 끝나거나 '죠/지요'
    ("polite", re.compile(r"(아요|어요|여요|해요|예요|에요|네요|세요|거든요|구요|죠|지요|요)$")),
    # 음슴체 — 명사형 어미
    ("nominal", re.compile(r"(했음|있음|없음|함|됨|임|음|슴)$")),
    # 했다체 — 맨 뒤
    ("plain", re.compile(r"(았다|었다|였다|이다|한다|된다|같다|싶다|다)$")),
)

#: 문장 경계. 줄바꿈도 경계로 본다 — 자소서는 문단으로 끊어 쓴다.
_SENTENCE = re.compile(r"[^.!?\n]+[.!?]*")

#: 문장 끝에서 떼어낼 것. 따옴표·괄호·말줄임표가 어미를 가린다.
_TRAIL = re.compile(r"[\s.!?…·\"'’”\)\]\}」』]+$")


@dataclass(frozen=True)
class Sentence:
    text: str
    start: int
    end: int
    tone: Tone | None


@dataclass(frozen=True)
class ToneAnalysis:
    sentences: tuple[Sentence, ...]

    @property
    def counts(self) -> dict[Tone, int]:
        out = dict.fromkeys(TONES, 0)
        for s in self.sentences:
            if s.tone is not None:
                out[s.tone] += 1
        return out

    @property
    def judged(self) -> tuple[Sentence, ...]:
        """문체를 판정한 문장만. 판정 못 한 문장은 비율 계산에서 뺀다."""
        return tuple(s for s in self.sentences if s.tone is not None)

    @property
    def main(self) -> Tone | None:
        """가장 많이 쓰인 문체. 판정한 문장이 없으면 None.

        같은 수면 `TONES` 순서(합니다체 우선)로 정한다 — 자소서의 표준이기 때문이다.
        """
        counts = self.counts
        if not any(counts.values()):
            return None
        return max(TONES, key=lambda t: (counts[t], -TONES.index(t)))

    @property
    def is_mixed(self) -> bool:
        return sum(1 for t in TONES if self.counts[t] > 0) > 1

    def off_tone(self, target: Tone) -> tuple[Sentence, ...]:
        """목표 문체가 아닌 문장. 화면에서 이 문장만 짚어 준다."""
        return tuple(s for s in self.judged if s.tone != target)


def ending_tone(sentence: str) -> Tone | None:
    """문장 하나의 문체. 판정할 수 없으면 None (명사로 끝나는 제목 등)."""
    tail = _TRAIL.sub("", sentence.strip())
    if not tail:
        return None
    for tone, pattern in _ENDINGS:
        if pattern.search(tail):
            return tone
    return None


def analyze(text: str) -> ToneAnalysis:
    """문장별 문체를 본다. 글을 바꾸지 않는다."""
    out: list[Sentence] = []
    for m in _SENTENCE.finditer(text):
        raw = m.group()
        if not raw.strip():
            continue
        out.append(Sentence(
            text=raw.strip(), start=m.start(), end=m.end(), tone=ending_tone(raw),
        ))
    return ToneAnalysis(sentences=tuple(out))
