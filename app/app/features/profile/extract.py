"""A14 — 사용자 말투 프로필 추출. **화이트리스트로만 센다.**

리라이팅(A6)·조정(A13)이 "이 사람처럼" 쓰게 하려면 그 사람의 말투를 알아야 한다.
그런데 말투를 저장하는 일은 **생각보다 위험하다.**

## ★ 자주 쓰는 "표현" 을 그대로 저장하면 그게 원문 조각이다

흔한 방법은 자주 나온 낱말·구를 뽑아 저장하는 것이다. 그러면 자소서 본문에서
**회사명·학교명·사람 이름·연락처**가 그대로 프로필에 들어온다. 프로필은 PII 가
아니라고 생각하고 만든 테이블이라, **거기서 PII 가 새면 아무도 예상하지 못한다.**
A5 가 `Finding` 에 값을 담지 않는 것과 같은 판단이다.

그래서 **셀 대상을 미리 정해 둔 기능어만** 센다(`_ENDINGS`·`_CONNECTIVES`).
사전에 없는 말은 **개수조차 세지 않는다** — 세면 그 값이 어딘가에 남는다.

| 저장하는 것 | 저장하지 않는 것 |
| --- | --- |
| 문장 평균 길이 · 긴 문장 비율 | 문장 자체 |
| 자주 쓰는 **종결 어미** (사전 안에서) | 내용어 · 명사 · 고유명사 |
| 자주 쓰는 **연결어** (사전 안에서) | 자주 쓰는 "표현" 일반 |
| 숫자 밀도 | 숫자 값 |

## ★ 표본이 적으면 말투가 아니다

`tasks.md` A14 가 **1,000자 이상**을 조건으로 둔 이유를 적어 둔다. 300자짜리 글 하나로
"이 사람은 평균 23자로 쓴다" 고 정하면, 그건 말투가 아니라 **그 글의 우연**이다.
그 프로필로 리라이팅을 하면 **엉뚱한 문체를 사용자에게 되돌려준다.**

## A13 과 겹치지 않는다

| | 보는 것 |
| --- | --- |
| **A13** | 문체 **종류** — 합니다체/해요체가 섞였는지 (교정) |
| **A14** | 그 안의 **개인 습관** — 어떤 종결·연결을 즐겨 쓰는지 (복원) |

A13 은 "틀린 것" 을 찾고, A14 는 "이 사람다운 것" 을 찾는다.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

#: 프로필을 만들 최소 글자 수 (`tasks.md` A14). 모듈 주석 ★ 참조.
MIN_SOURCE_CHARS = 1000

#: 종결 표현 화이트리스트. **긴 것부터** 본다 — "했습니다" 가 "습니다" 보다 먼저여야 한다.
#: A1 PERSON·A3 질의 분류·A13 문체 판정에서 반복됐던 **규칙 우선순위** 문제다.
_ENDINGS: tuple[str, ...] = (
    "되었습니다", "하였습니다", "였습니다", "았습니다", "었습니다", "했습니다",
    "있습니다", "없습니다", "싶습니다", "같습니다", "겠습니다", "입니다", "합니다",
    "됩니다", "습니다",
    "했어요", "이에요", "예요", "어요", "아요", "해요",
    "했다", "이다", "한다", "된다",
    "했음", "입니", "함", "임", "됨",
)

#: 연결·접속 표현 화이트리스트. 전부 기능어라 저장해도 내용이 새지 않는다.
_CONNECTIVES: tuple[str, ...] = (
    "그래서", "그러나", "하지만", "그리고", "또한", "따라서", "그런데",
    "특히", "무엇보다", "결국", "다만", "반면", "예를 들어", "즉",
    "이를 통해", "그 결과", "덕분에", "때문에",
)

#: 프로필에 남길 상위 개수. 많이 남길수록 **문체 지문**이 선명해진다 — 적게 남긴다.
TOP_N = 3

#: 이 길이를 넘는 문장을 "긴 문장" 으로 센다 (A7 `MAX_SENTENCE_LEN` 과 같은 값).
LONG_SENTENCE_LEN = 90

_SENTENCE = re.compile(r"[^.!?\n]+[.!?]*")

#: 다른 모듈(리라이팅 말투 샘플)이 쓰는 이름. 기능어 화이트리스트라 프롬프트에 넣어도 내용이 새지 않는다
CONNECTIVES = _CONNECTIVES

#: 문단 경계. 빈 줄만 보면 **줄바꿈 하나로 단락을 나눈 글이 한 문단**으로 세어진다 —
#: 자소서 문항 답변에서 줄바꿈은 거의 항상 문단 의도다 (입력창이 자동 줄바꿈하므로
#: 수동 개행은 사용자가 일부러 넣은 것이다).
_PARAGRAPH = re.compile(r"\n+")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_TRAIL = re.compile(r"[\s.!?…·\"'’”\)\]\}」』]+$")

#: PII 토큰. 섞여 있으면 사용자가 보는 원문이 아니다.
_TOKEN = re.compile(r"\[\[[A-Z_]+_\d+\]\]")


class NotEnoughText(ValueError):
    """글이 모자라 프로필을 만들 수 없다. 몇 자가 더 필요한지 메시지에 담는다."""


class TokenizedTextError(ValueError):
    """토큰화된 본문으로 프로필을 만들려 했다.

    토큰(``[[PHONE_1]]``)이 섞인 글로 문장 길이를 세면 **실제와 다른 값**이 나온다.
    저장된 본문이 아니라 **사용자가 보는 원문**으로 만들어야 한다 (A13 `counter` 와 같은 판단).
    """


@dataclass(frozen=True)
class WritingStyle:
    """추출한 말투. **여기에 원문 조각은 없다.**

    문자열이 들어가는 두 필드는 화이트리스트(`_ENDINGS`·`_CONNECTIVES`)에서만 나온다.
    """

    avg_sentence_len: int
    long_sentence_ratio: int
    paragraph_avg_sentences: int
    numeric_density: int
    endings: tuple[str, ...]
    connectives: tuple[str, ...]
    source_chars: int
    sentence_count: int


def _sentences(text: str) -> list[str]:
    return [m.group().strip() for m in _SENTENCE.finditer(text) if m.group().strip()]


def _ending_of(sentence: str) -> str | None:
    """문장의 종결 표현. 화이트리스트에 없으면 None — **세지 않는다.**"""
    tail = _TRAIL.sub("", sentence)
    for ending in _ENDINGS:
        if tail.endswith(ending):
            return ending
    return None


def extract(text: str) -> WritingStyle:
    """사용자가 쓴 글에서 말투를 뽑는다.

    ``MIN_SOURCE_CHARS`` 미만이면 `NotEnoughText` 를 올린다 — 표본이 적으면 말투가
    아니라 그 글의 우연이다.
    """
    if _TOKEN.search(text):
        raise TokenizedTextError(
            "PII 토큰이 섞여 있습니다. 말투는 사용자가 보는 원문으로 뽑아야 합니다"
        )

    length = len(text)
    if length < MIN_SOURCE_CHARS:
        raise NotEnoughText(
            f"말투를 뽑으려면 {MIN_SOURCE_CHARS}자 이상이 필요합니다 "
            f"(지금 {length}자, {MIN_SOURCE_CHARS - length}자 부족)"
        )

    sentences = _sentences(text)
    if not sentences:
        raise NotEnoughText("문장을 찾지 못했습니다")

    lengths = [len(s) for s in sentences]
    long_count = sum(1 for n in lengths if n > LONG_SENTENCE_LEN)
    paragraphs = [p for p in _PARAGRAPH.split(text) if p.strip()] or [text]

    endings = Counter(e for s in sentences if (e := _ending_of(s)) is not None)
    connectives = Counter({c: n for c in _CONNECTIVES if (n := text.count(c))})

    return WritingStyle(
        avg_sentence_len=round(sum(lengths) / len(lengths)),
        long_sentence_ratio=round(long_count * 100 / len(sentences)),
        paragraph_avg_sentences=max(1, round(len(sentences) / len(paragraphs))),
        numeric_density=round(len(_NUMBER.findall(text)) * 1000 / length),
        endings=tuple(w for w, _ in endings.most_common(TOP_N)),
        connectives=tuple(w for w, _ in connectives.most_common(TOP_N)),
        source_chars=length,
        sentence_count=len(sentences),
    )
