"""A6 — 자소서 리라이팅. **고른 구간만** 옵션에 맞춰 다시 쓴 후보 3개를 만든다.

A7 과 나누는 기준은 "무엇을 돌려주는가" 다.

    A7 맞춤법·문장 개선   고칠 **자리**를 짚어 준다. 글은 사용자가 고친다
    A6 리라이팅          고른 구간을 **통째로 다시 쓴 글**을 준다. 사용자는 고른다
    A13 글자 수·문체 조정  제한·문체라는 **기준에 맞춘 한 벌**을 준다

## ★ 후보 3개는 호출 **한 번**에서 받는다

후보마다 따로 부르면 3회다. 여기에 5,000자 분할이 곱해지면 상한(A2
``DEFAULT_MAX_CALLS`` = 4)을 금방 넘는다. 조각 하나에 "후보 3개를 쓰라" 고
시키면 호출 수가 **조각 수와 같아져** 분할 예산을 그대로 쓸 수 있다.

## ★ 나누는 것은 **모델에 보낼 때뿐**이다

가드레일(A8)은 고른 구간을 **통째로 먼저** 검사한다. 조각내서 검사하면
조각 경계에 걸친 민감정보를 놓친다 — ``010-1234`` 와 ``-5678`` 로 갈리면
둘 다 전화번호가 아니다.

## ★ 변경 하이라이트는 B4 의 diff 를 그대로 쓴다

`resumes.service.diff_segments` 가 이미 단어 단위로 같은 일을 한다. 여기서
또 만들면 **같은 글에 대해 두 화면이 다른 차이를 보여준다.**
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from app.features.style.tone import DEFAULT_TONE, TONE_NAMES, TONES, Tone
from app.guardrail import DEFAULT_MAX_CALLS

#: 돌려줄 후보 수. tasks.md A6 이 정한 값이다.
CANDIDATE_COUNT = 3

#: 모델에 한 번에 보낼 글자 수. tasks.md A6 "5,000자 초과 분할".
MAX_CHUNK_CHARS = 5000

#: 조각 수 상한. A2 의 호출 상한과 **같은 값이어야 한다** — 더 크게 잡으면
#: 조각을 만들어 놓고 `LlmBudgetExceeded` 로 거절당한다. 토큰은 이미 쓴 뒤다.
MAX_PARTS = DEFAULT_MAX_CALLS

#: 고를 수 있는 구간의 최대 길이.
MAX_SELECTION_LEN = MAX_CHUNK_CHARS * MAX_PARTS

#: 넣어 달라고 할 수 있는 키워드 수. 많이 넣을수록 **문장이 키워드 나열이 된다.**
MAX_KEYWORDS = 10

#: 키워드 하나의 길이. 문장을 통째로 넣는 것을 막는다.
MAX_KEYWORD_LEN = 30

Length = Literal["shorter", "similar", "longer"]
LENGTHS: tuple[Length, ...] = ("shorter", "similar", "longer")
DEFAULT_LENGTH: Length = "similar"

#: 길이 옵션을 모델에게 줄 지시로 바꾼 것.
#:
#: ★ 비율로 적는다. "300자로 써라" 처럼 절대값을 주면 **원문이 짧을 때
#:   없는 내용을 지어내서 채운다.** 분량을 맞추려고 사실을 만드는 것이
#:   리라이팅에서 가장 위험한 실패다.
LENGTH_RULES: dict[Length, str] = {
    "shorter": "원문보다 20% 정도 짧게 씁니다. 내용을 지우지 말고 표현을 줄입니다.",
    "similar": "원문과 비슷한 길이로 씁니다.",
    "longer": "원문보다 20% 정도 길게 씁니다. **없는 사실을 보태지 말고**, "
              "이미 있는 내용을 더 또렷하게 풀어 씁니다.",
}

LENGTH_NAMES: dict[Length, str] = {
    "shorter": "짧게",
    "similar": "비슷하게",
    "longer": "길게",
}

#: 후보 사이의 구분선. 모델이 줄 머리에 쓴다.
#:
#: ★ 본문에 나올 수 없는 모양이어야 한다. 자소서에 '---' 나 '1.' 은 흔하다.
CANDIDATE_MARK = "###후보"
_CANDIDATE_RE = re.compile(rf"^{re.escape(CANDIDATE_MARK)}\s*(\d+)\s*$", re.MULTILINE)

#: 문단 경계. 빈 줄 하나로 본다.
_PARAGRAPH = re.compile(r"\n\s*\n")

#: 문장 경계. 한국어 종결 어미 뒤와 문장 부호 뒤에서 끊는다.
#: 뒤에 공백이 와야 끊는다 — `3.5%` 의 마침표에서 끊기지 않게 한다.
_SENTENCE = re.compile(r"(?<=[.!?。？！])\s+|(?<=다)\.\s+")


class RewriteOptionError(ValueError):
    """옵션이 규약에 맞지 않는다. 라우터가 400 으로 바꾼다."""


@dataclass(frozen=True)
class RewriteOptions:
    """리라이팅 옵션 (tasks.md A6 "톤, 길이, 키워드").

    세 가지 모두 **기본값이 있다.** 아무것도 고르지 않아도 리라이팅은 된다 —
    옵션을 고르게 강제하면 "그냥 다시 써 줘" 를 못 하게 된다.
    """

    tone: Tone = DEFAULT_TONE
    length: Length = DEFAULT_LENGTH
    keywords: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.tone not in TONES:
            raise RewriteOptionError(f"문체는 {TONES} 중 하나여야 합니다: {self.tone!r}")
        if self.length not in LENGTHS:
            raise RewriteOptionError(f"길이는 {LENGTHS} 중 하나여야 합니다: {self.length!r}")
        if len(self.keywords) > MAX_KEYWORDS:
            raise RewriteOptionError(f"키워드는 {MAX_KEYWORDS}개까지 넣을 수 있습니다")
        for word in self.keywords:
            if not word.strip():
                raise RewriteOptionError("빈 키워드는 넣을 수 없습니다")
            if len(word) > MAX_KEYWORD_LEN:
                raise RewriteOptionError(
                    f"키워드 하나는 {MAX_KEYWORD_LEN}자까지입니다: {word[:20]!r}"
                )

    def instructions(self) -> str:
        """옵션을 모델에게 줄 지시 문단으로 바꾼다.

        ★ A14 말투 프로필과 같은 생각이다 — **무엇이 모델에 가는지 사용자가 볼 수
          있어야 한다.** 그래서 응답에도 이 문단을 그대로 실어 보낸다.
        """
        lines = [
            f"- 문체는 {TONE_NAMES[self.tone]}로 씁니다.",
            f"- {LENGTH_RULES[self.length]}",
        ]
        if self.keywords:
            words = " · ".join(self.keywords)
            lines.append(
                f"- 다음 말을 자연스럽게 넣습니다: {words}. "
                "넣을 자리가 없으면 **억지로 넣지 않습니다.**"
            )
        return "\n".join(lines)


def normalize_keywords(words: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """앞뒤 공백을 떼고 빈 것과 중복을 없앤다. 순서는 받은 대로 둔다.

    중복을 지우는 이유 — 같은 말이 두 번 들어가면 모델이 **두 번 넣으려 한다.**
    """
    seen: dict[str, None] = {}
    for word in words:
        stripped = word.strip()
        if stripped:
            seen.setdefault(stripped, None)
    return tuple(seen)


def split_selection(text: str, *, max_chars: int = MAX_CHUNK_CHARS) -> tuple[str, ...]:
    """모델에 보낼 조각으로 나눈다. 짧으면 나누지 않는다.

    문단 → 문장 → 글자 순으로 **덜 아픈 자리부터** 끊는다. 글자에서 끊으면
    문장이 반 토막 나고, 반 토막 난 문장을 다시 쓰라고 하면 모델이 앞뒤를
    지어낸다.
    """
    if len(text) <= max_chars:
        return (text,)

    parts: list[str] = []
    current = ""
    for block in _blocks(text, max_chars):
        if not current:
            current = block
        elif len(current) + len(block) <= max_chars:
            current += block
        else:
            parts.append(current)
            current = block
    if current:
        parts.append(current)
    return tuple(parts)


def _blocks(text: str, max_chars: int) -> list[str]:
    """끊어도 되는 가장 큰 덩어리들. 구분자를 **버리지 않는다** —
    합치면 원문이 그대로 나와야 한다."""
    out: list[str] = []
    for para in _split_keeping(text, _PARAGRAPH):
        if len(para) <= max_chars:
            out.append(para)
            continue
        for sentence in _split_keeping(para, _SENTENCE):
            if len(sentence) <= max_chars:
                out.append(sentence)
            else:
                # 마지막 수단. 문장 하나가 5,000자면 통째로는 못 보낸다
                out += [sentence[i:i + max_chars] for i in range(0, len(sentence), max_chars)]
    return out


def _split_keeping(text: str, pattern: re.Pattern[str]) -> list[str]:
    """구분자를 앞 조각 끝에 붙여서 나눈다."""
    out: list[str] = []
    last = 0
    for m in pattern.finditer(text):
        out.append(text[last:m.end()])
        last = m.end()
    if last < len(text):
        out.append(text[last:])
    return out or [text]


def build_part_prompt(
    part: str,
    options: RewriteOptions,
    *,
    template_body: str | None = None,
    profile_fragment: str = "",
    part_index: int = 0,
    part_total: int = 1,
) -> str:
    """조각 하나를 다시 쓰라는 프롬프트.

    ``template_body`` 는 B9 활성 템플릿이다. 없으면 내장 기본값으로 쓴다 —
    **활성 템플릿이 없다고 기능이 멈추면 안 된다** (운영자가 첫 템플릿을
    등록하기 전까지 아무도 리라이팅을 못 쓰게 된다).
    """
    head = template_body if template_body else DEFAULT_TEMPLATE_BODY
    rules = [options.instructions()]
    if profile_fragment:
        rules.append(profile_fragment)
    if part_total > 1:
        rules.append(
            f"- 이 글은 긴 글의 {part_index + 1}/{part_total} 조각입니다. "
            "앞뒤를 짐작해 **없는 내용을 덧붙이지 않습니다.**"
        )
    return (
        f"{head}\n\n"
        f"{_candidate_rule()}\n\n"
        f"{chr(10).join(rules)}\n\n"
        f"--- 글 ---\n{part}"
    )


def _candidate_rule() -> str:
    marks = " ".join(f"{CANDIDATE_MARK}{i}" for i in range(1, CANDIDATE_COUNT + 1))
    return (
        f"후보를 정확히 {CANDIDATE_COUNT}개 씁니다. 각 후보 앞 줄에 {marks} 를 "
        "그 줄에만 씁니다. 다른 설명은 쓰지 않습니다."
    )


DEFAULT_TEMPLATE_BODY = (
    "아래 자기소개서 구간을 다시 써 주십시오.\n"
    "사실을 바꾸거나 없는 경험을 만들지 않습니다. 숫자는 있는 그대로 둡니다."
)


def parse_candidates(text: str, *, want: int = CANDIDATE_COUNT) -> tuple[str, ...]:
    """모델 응답에서 후보를 꺼낸다.

    ★ **못 꺼내면 빈 결과를 돌려준다.** 모델이 형식을 어겼을 때 응답 전체를
      후보 하나로 치면, 설명문이나 사과문이 자소서 본문으로 저장된다.
    """
    marks = list(_CANDIDATE_RE.finditer(text))
    if not marks:
        return ()
    out: list[str] = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[m.end():end].strip()
        if body:
            out.append(body)
    return tuple(out[:want])


def join_candidates(per_part: list[tuple[str, ...]], *, want: int = CANDIDATE_COUNT) -> tuple[str, ...]:
    """조각별 후보를 **후보별로** 이어 붙인다.

        조각1 [후보1, 후보2, 후보3]        후보1 = 조각1-1 + 조각2-1
        조각2 [후보1, 후보2, 후보3]   →    후보2 = 조각1-2 + 조각2-2

    ★ 어느 조각이든 후보가 모자라면 **그 번호는 버린다.** 조각 하나를 빼고
      이으면 사용자는 **글 가운데가 사라진 것을 모른 채** 저장한다.
    """
    if not per_part:
        return ()
    usable = min(len(c) for c in per_part)
    return tuple(
        "\n\n".join(part[i] for part in per_part) for i in range(min(usable, want))
    )
