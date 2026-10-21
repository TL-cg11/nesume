"""A7 1차 — 규칙 기반 문장 검사기.

LLM 을 부르기 **전에** 규칙으로 먼저 거른다. 이유 세 가지다.

1. 값이 싸고 빠르다. 조사 오류 하나 고치자고 모델을 부를 이유가 없다.
2. **결과가 항상 같다.** 같은 글을 두 번 검사하면 같은 제안이 나온다.
   모델은 같은 글에도 다른 답을 주므로 "아까는 괜찮다더니" 가 생긴다.
3. **왜 그런지 설명할 수 있다.** 규칙 ID 가 근거다.

그래서 규칙이 잡을 수 있는 것은 규칙이 잡고, 모델에는 **문맥이 필요한 것만** 맡긴다.

★ 규칙은 오탐이 거의 없는 것만 넣는다. 교정 제안의 오탐은 사용자가 거절하면 그만이지만,
  오탐이 많으면 제안 목록 전체를 안 보게 된다. 1차 프로젝트에서 탐지 오탐 0%% 를
  목표로 했던 것과 같은 판단이다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from app.features.writing.hangul import has_final_consonant, has_rieul_final
from app.features.writing.suggestions import Suggestion, SuggestionKind

#: 한 문장이 이보다 길면 나누기를 권한다 (공백 포함).
#: 자소서는 글자 수 제한이 있어 긴 문장이 유리해 보이지만, 읽는 사람은 평가자다.
MAX_SENTENCE_LEN = 90

#: 받침 유무로 갈리는 조사 쌍 — (받침 있을 때, 없을 때)
#:
#: ★ '이/가' 와 '과/와' 는 **뺐다.**
#:   '이' 는 지시어로도 쓰이고("이 프로젝트"), '과' 는 낱말의 일부가 된다("사과").
#:   정규식만으로는 조사인지 아닌지 가릴 수 없어 오탐이 난다.
_PARTICLE_PAIRS: tuple[tuple[str, str], ...] = (
    ("은", "는"), ("을", "를"),
)

#: 조사 뒤에 **공백이나 문장부호가 와야** 한다.
#: 글 끝의 낱말("지은", "사과")이 조사로 잡히는 것을 막는다.
_PARTICLE_RE = re.compile(r"([가-힣])(은|는|을|를|으로|로)(?=[\s,.)])")

#: ⚠ 남은 한계: 관형형 어미와 구분하지 못한다.
#:   "지은 보고서" 의 '지은'(짓다)을 "지+은" 으로 읽어 '지는' 을 제안할 수 있다.
#:   형태소 분석 없이는 해결되지 않아, 조사 제안은 **medium 신뢰도**로 표시하고
#:   글쓴이가 거절할 수 있게 둔다. 알려진 오탐 사례는 테스트에 적어 두었다.

#: 이중피동. '되어지다·불려지다' 처럼 피동이 두 번 들어간 형태.
#: 고치는 방향이 분명해 오탐이 거의 없다.
_DOUBLE_PASSIVE: tuple[tuple[str, str, str], ...] = (
    ("되어집니다", "됩니다", "되다 + 어지다 가 겹쳤습니다"),
    ("되어졌습니다", "되었습니다", "되다 + 어지다 가 겹쳤습니다"),
    ("되어진", "된", "되다 + 어지다 가 겹쳤습니다"),
    ("불려집니다", "불립니다", "피동이 두 번 들어갔습니다"),
    ("보여집니다", "보입니다", "피동이 두 번 들어갔습니다"),
    ("쓰여집니다", "쓰입니다", "피동이 두 번 들어갔습니다"),
    ("잊혀집니다", "잊힙니다", "피동이 두 번 들어갔습니다"),
    ("나뉘어집니다", "나뉩니다", "피동이 두 번 들어갔습니다"),
)

#: 의존명사 띄어쓰기. 앞말과 붙여 쓰기 쉬운 것만 좁게 잡는다.
_BOUND_NOUNS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"([가-힣])(수)(있|없)"), r"\1 \2 \3", "의존명사 '수' 는 띄어 씁니다"),
    (re.compile(r"(할|한|된|했을)(때)"), r"\1 \2", "의존명사 '때' 는 띄어 씁니다"),
    (re.compile(r"([가-힣])(뿐)(입니다|이었)"), r"\1 \2\3", "의존명사 '뿐' 은 띄어 씁니다"),
)

#: 자소서에 흔한 상투어. **고치지 않고 안내만** 한다 —
#: 무엇으로 바꿀지는 글쓴이만 안다. 대안을 멋대로 넣으면 사실이 아닌 문장이 된다.
_CLICHES: tuple[tuple[str, str], ...] = (
    ("최선을 다했습니다", "무엇을 어떻게 했는지로 바꾸면 더 구체적입니다"),
    ("열심히 했습니다", "무엇을 얼마나 했는지 숫자로 적어 보십시오"),
    ("많은 것을 배웠습니다", "무엇을 배웠고 어디에 썼는지 적어 보십시오"),
    ("책임감이 강합니다", "책임감을 보여준 사례 하나로 바꾸면 더 설득력 있습니다"),
    ("성실하게", "성실함이 드러난 행동으로 바꾸어 보십시오"),
    ("다양한 경험", "어떤 경험인지 두세 개로 구체화해 보십시오"),
    ("원활한 소통", "누구와 무엇을 어떻게 조율했는지 적어 보십시오"),
)


@dataclass(frozen=True)
class Rule:
    rule_id: str
    kind: SuggestionKind
    #: 글을 받아 제안 목록을 돌려주는 함수
    run: Callable[[str], list[Suggestion]]


# --------------------------------------------------------------------------
# 개별 검사
# --------------------------------------------------------------------------

def _correct_particle(last_char: str, particle: str) -> str | None:
    """올바른 조사를 돌려준다. 이미 맞으면 None."""
    has_final = has_final_consonant(last_char)

    if particle in {"으로", "로"}:
        correct = "로" if (not has_final or has_rieul_final(last_char)) else "으로"
    else:
        correct = None
        for with_final, without_final in _PARTICLE_PAIRS:
            if particle in (with_final, without_final):
                correct = with_final if has_final else without_final
                break
        if correct is None:
            return None

    return None if correct == particle else correct


def check_particles(text: str) -> list[Suggestion]:
    """조사가 앞 글자의 받침과 맞는지 본다."""
    out: list[Suggestion] = []
    for m in _PARTICLE_RE.finditer(text):
        last_char, particle = m.group(1), m.group(2)
        correct = _correct_particle(last_char, particle)
        if correct is None:
            continue
        # 안내 문구의 조사도 우리 규칙으로 고른다. 스스로 지키지 않으면 설득력이 없다
        josa = "이" if has_final_consonant(correct[-1]) else "가"
        out.append(Suggestion(
            kind="particle", rule_id="WR_PARTICLE",
            start=m.start(2), end=m.end(2),
            original=particle, suggested=correct,
            reason=f"'{last_char}' 뒤에는 '{correct}'{josa} 맞습니다",
            confidence="medium",
        ))
    return out


def check_double_passive(text: str) -> list[Suggestion]:
    """이중피동을 찾는다."""
    out: list[Suggestion] = []
    for wrong, right, reason in _DOUBLE_PASSIVE:
        for m in re.finditer(re.escape(wrong), text):
            out.append(Suggestion(
                kind="passive", rule_id="WR_DOUBLE_PASSIVE",
                start=m.start(), end=m.end(),
                original=wrong, suggested=right, reason=reason,
            ))
    return out


def check_spacing(text: str) -> list[Suggestion]:
    """의존명사 띄어쓰기."""
    out: list[Suggestion] = []
    for pattern, repl, reason in _BOUND_NOUNS:
        for m in re.finditer(pattern, text):
            fixed = m.expand(repl)
            if fixed == m.group(0):
                continue
            out.append(Suggestion(
                kind="spacing", rule_id="WR_SPACING",
                start=m.start(), end=m.end(),
                original=m.group(0), suggested=fixed, reason=reason,
            ))
    return out


def check_cliches(text: str) -> list[Suggestion]:
    """상투어에 안내만 붙인다. 대안은 넣지 않는다."""
    out: list[Suggestion] = []
    for phrase, reason in _CLICHES:
        for m in re.finditer(re.escape(phrase), text):
            out.append(Suggestion(
                kind="cliche", rule_id="WR_CLICHE",
                start=m.start(), end=m.end(),
                original=phrase,
                suggested="",  # ★ 자동 치환하지 않는다
                reason=reason,
            ))
    return out


_SENTENCE_END = re.compile(r"[.!?]\s*|\n+")


def check_long_sentences(text: str) -> list[Suggestion]:
    """너무 긴 문장을 알려준다. 어디서 끊을지는 글쓴이가 정한다."""
    out: list[Suggestion] = []
    cursor = 0
    for m in _SENTENCE_END.finditer(text):
        sentence = text[cursor : m.start()]
        if len(sentence.strip()) > MAX_SENTENCE_LEN:
            out.append(Suggestion(
                kind="long_sentence", rule_id="WR_LONG_SENTENCE",
                start=cursor, end=m.start(),
                original=sentence, suggested="",
                reason=f"{len(sentence.strip())}자입니다. {MAX_SENTENCE_LEN}자를 넘으면 두 문장으로 나누는 편이 읽기 좋습니다",
            ))
        cursor = m.end()

    tail = text[cursor:]
    if len(tail.strip()) > MAX_SENTENCE_LEN:
        out.append(Suggestion(
            kind="long_sentence", rule_id="WR_LONG_SENTENCE",
            start=cursor, end=len(text),
            original=tail, suggested="",
            reason=f"{len(tail.strip())}자입니다. 두 문장으로 나누는 편이 읽기 좋습니다",
        ))
    return out


RULES: tuple[Rule, ...] = (
    Rule("WR_PARTICLE", "particle", check_particles),
    Rule("WR_DOUBLE_PASSIVE", "passive", check_double_passive),
    Rule("WR_SPACING", "spacing", check_spacing),
    Rule("WR_CLICHE", "cliche", check_cliches),
    Rule("WR_LONG_SENTENCE", "long_sentence", check_long_sentences),
)


def check(text: str) -> list[Suggestion]:
    """1차 검사. 부작용이 없고 LLM 을 부르지 않는다.

    위치 순서로 정렬해 돌려준다. 화면에서 글을 따라 내려가며 보기 때문이다.
    """
    if not text or not text.strip():
        return []

    found: list[Suggestion] = []
    for rule in RULES:
        found.extend(rule.run(text))

    found.sort(key=lambda s: (s.start, s.end, s.rule_id))
    return found
