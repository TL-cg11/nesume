"""A11 조립 — 공고 키워드 추출 + 매칭 분석.

    1. 공고 준비    A1 mask → C5 preprocess        (외부 텍스트를 다루기 전에)
    2. 키워드 추출  규칙만. LLM 없음                (keywords.extract)
    3. 대조         자소서 · 경험과 세 갈래로       (coverage.compare)
    4. 질문 생성    빠진 요건 → **질문**            규칙만
    5. 반영 문장    경험에만 있는 것 → 한 문장      A8 경유 LLM (선택)
    6. 검증         모델이 **없는 사실을 넣었는지**  → 넣었으면 버린다

★ 공고 본문은 모델에 보내지 않는다. 모델에 가는 것은 **키워드 낱말과 사용자 자기
  경험 글**뿐이다. 공고는 외부 untrusted 텍스트라 프롬프트에 넣는 양이 곧 인젝션
  표면이다 — 테스트로 "공고 문장이 프롬프트에 없음"을 고정한다 (A10 에서 배운 방법).

★ 빠진 요건에는 **문장을 제안하지 않는다.** 질문만 돌려준다.
  "Python 이 빠졌습니다 → 'Python 으로 개발했습니다' 를 넣으세요" 는 **해 본 적 없는
  일을 쓰게 만든다.** 자소서의 허위 기재는 면접에서 드러나고 그 책임은 사용자가 진다.
  A7 에서 "STAR 요소가 2개 이하면 모델을 부르지 않는다" 와 같은 판단이다.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.features.matching import keywords as kw_mod
from app.features.matching import vocab
from app.features.matching.coverage import CoverageReport, UserEvidence, compare
from app.features.matching.keywords import Keyword, PostingFields
from app.guardrail import (
    DEFAULT_SYSTEM_PROMPT,
    Guardrail,
    LlmRequest,
    LlmUnavailable,
    RequestContext,
)
from app.pii import mask
from app.retrieval.preprocess import preprocess_external_text

FEATURE = "matching.analyze"

#: 모델 제안 한 줄의 구분자. A7 과 같은 값을 쓴다 — 본문에 섞이지 않는 기호여야 한다.
SEP = "|||"

#: 모델에게 받을 문장의 최대 개수. 상한이 없으면 경험마다 참견한다.
MAX_HINTS = 5

#: 질문 문구. 사전 분류별로 고른다.
#:
#: ★ 낱말 **뒤에 조사를 붙이지 않는다.** "엑셀를", "Python을" 처럼 어긋나기 때문이다.
#:   받침에 맞춰 조사를 고르는 코드는 A7(`features/writing/hangul.py`)에 있지만 그쪽은
#:   아직 별도 브랜치이고, 같은 것을 두 벌 두지 않으려고 **문구를 조사 없이** 썼다.
_QUESTION_BY_CATEGORY = {
    "cert": "「{text}」 자격이 있습니까? 취득 예정이라면 그 사실을 쓰는 것도 방법입니다.",
    "language": "{text} 사용 경험이 있습니까? 수업 과제·개인 프로젝트도 경험입니다.",
    "framework": "{text} 사용 경험이 있습니까? 수업 과제·개인 프로젝트도 경험입니다.",
    "data": "{text} 사용 경험이 있습니까?",
    "cloud": "{text} 사용 경험이 있습니까?",
    "tool": "{text} 사용 경험이 있습니까?",
    "office": "{text} 활용 수준은 어느 정도입니까? 등급·자격이 있으면 함께 씁니다.",
    "domain": "{text} 관련 경험이 있습니까? 아르바이트·동아리 활동도 포함됩니다.",
}
_QUESTION_DEFAULT = "공고가 요구하는 요건입니다 — 「{text}」. 해당하는 경험이 있습니까?"

#: 경험 글과 빠진 낱말을 **한 덩어리로** 가드레일에 넘길 때 쓰는 표시.
#:
#: ★ 본문에 나올 수 없는 모양이어야 한다. 사용자가 이 글자를 그대로 쳐 넣으면
#:   가르는 자리가 어긋나 프롬프트의 두 칸이 섞인다 — 검사는 이미 통째로 끝난
#:   뒤라 보안에는 영향이 없고, 모델이 받는 글의 묶음만 어긋난다.
_GUARD_SEP = "\n<<<MATCHING_KEYWORDS>>>\n"

#: 질문 목록 맨 앞에 붙는 말. 없으면 사용자는 질문을 **채워야 할 빈칸**으로 읽는다.
NO_INVENTION_NOTICE = "해당 경험이 없으면 쓰지 않는 것이 맞습니다. 없는 경험은 면접에서 드러납니다."

_PROMPT = """아래는 지원자 본인이 적어 둔 경험입니다. 공고가 요구하는 낱말이
이 경험 안에 들어 있는데 자기소개서에는 빠져 있습니다.

규칙:
- **경험에 적힌 사실만** 씁니다. 숫자·기간·기술을 새로 만들지 않습니다.
- 낱말을 억지로 넣지 말고, 그 낱말이 자연스럽게 들어간 한 문장을 만듭니다.
- 한 줄에 하나씩, 아래 형식으로만 씁니다. 다른 설명은 쓰지 않습니다.

형식:  낱말{sep}문장

최대 {limit}개까지만 씁니다.

--- 경험 ---
{experiences}

--- 자기소개서에 빠진 낱말 ---
{missing}"""


@dataclass(frozen=True)
class Hint:
    """경험에만 있는 요건을 자소서에 넣을 때 쓸 문장 하나.

    ★ 사용자가 그대로 붙여 넣을 수 있는 글이라 **근거를 반드시 함께 보여준다**
      (`experiences`). 어느 경험에서 나왔는지 모르면 사실 확인을 할 수 없다.
    """

    keyword: str
    sentence: str
    experiences: tuple[str, ...]
    #: 모델이 만든 문장이라 근거를 댈 수 없다. 화면에서 "확인 필요" 로 표시한다
    confidence: str = "medium"


@dataclass(frozen=True)
class AnalyzeResult:
    keywords: tuple[Keyword, ...]
    report: CoverageReport
    #: 빠진 요건에 대한 **질문**. 문장 제안이 아니다
    questions: tuple[str, ...] = ()
    #: 경험에만 있는 요건을 자소서에 넣을 문장 (LLM)
    hints: tuple[Hint, ...] = ()
    #: C5 가 공고에서 찾은 인젝션 신호. 감사·대시보드(D15)로 넘긴다
    posting_flags: tuple[str, ...] = ()
    #: 공고가 길이 상한에 걸려 잘렸는가
    posting_truncated: bool = False
    llm_used: bool = False
    llm_unavailable: bool = False
    blocked_reason: str | None = None
    #: 모델이 없는 사실을 넣어 **버린** 문장 수. 0 이 아니면 측정에 남겨야 한다
    dropped_hints: int = 0
    counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class PreparedPosting:
    """외부 텍스트를 다룰 수 있게 손질한 공고."""

    fields: PostingFields
    flags: tuple[str, ...]
    truncated: bool


def prepare_posting(posting: PostingFields) -> PreparedPosting:
    """공고의 각 필드를 **A1 마스킹 → C5 전처리** 순서로 손질한다.

    순서는 `docs/C5.md` 가 정했다 — C5 는 PII 를 다루지 않으므로 A1 이 먼저다.
    공고 본문(`JOB_CONT`)에는 담당자 연락처가 섞여 들어온다.

    필드마다 따로 돌리는 이유는 **어느 필드에서 나온 요건인지**를 뒤에서 쓰기 때문이다.
    한 덩어리로 합쳐 처리하면 그 근거가 사라진다.
    """
    cleaned: dict[str, str | None] = {}
    flags: list[str] = []
    truncated = False

    for name, value in posting.texts():
        result = preprocess_external_text(mask(value))
        cleaned[name] = result.text
        flags.extend(result.flags)
        truncated = truncated or result.truncated

    return PreparedPosting(
        fields=PostingFields(**cleaned),
        flags=tuple(dict.fromkeys(flags)),
        truncated=truncated,
    )


def questions_for(report: CoverageReport) -> tuple[str, ...]:
    """빠진 요건을 **질문**으로 바꾼다. 필수부터.

    문장을 제안하지 않는 이유는 모듈 주석에 적었다.
    """
    out: list[str] = []
    for m in report.of_status("missing"):
        template = _QUESTION_BY_CATEGORY.get(m.keyword.category, _QUESTION_DEFAULT)
        out.append(template.format(text=m.keyword.text))
    return tuple(out)


def _allowed_terms(evidence: UserEvidence, report: CoverageReport) -> frozenset[str]:
    """모델 문장에 나와도 되는 사전 항목.

    사용자가 쓴 글·경험에 있는 것과, 공고 키워드다. 그 밖의 기술이 문장에 나오면
    **모델이 지어낸 것**이다.
    """
    keys = set(vocab.matched_keys(evidence.resume_text))
    for e in evidence.experiences:
        keys |= vocab.matched_keys(e.haystack())
    for m in report.matches:
        if m.keyword.term is not None:
            keys.add(m.keyword.term.key)
    return frozenset(keys)


def parse_hints(
    reply: str,
    *,
    report: CoverageReport,
    evidence: UserEvidence,
) -> tuple[tuple[Hint, ...], int]:
    """모델 응답을 문장 목록으로 바꾸고 **검증한다.**

    버리는 경우가 셋이다.

    1. 대상 낱말이 `in_experience_only` 목록에 없다 — 모델이 다른 요건을 건드렸다
    2. 문장에 그 낱말이 없다 — 낱말을 넣는 것이 일인데 안 넣었다
    3. **문장에 사용자 글·경험에 없는 기술이 나온다** — 지어낸 것이다

    3번이 A11 에서 가장 중요한 검사다. "Docker 로 배포했습니다" 를 만들라고 했는데
    "Docker 와 Kubernetes 로 배포했습니다" 가 돌아오면 **쓴 적 없는 기술이 자소서에
    들어간다.** 돌려준 두 번째 값은 버린 개수이며, 0 이 아니면 측정에 남겨야 한다.
    """
    targets = {m.keyword.text.casefold(): m for m in report.writable_now}
    allowed = _allowed_terms(evidence, report)

    hints: list[Hint] = []
    dropped = 0
    used: set[str] = set()

    for line in reply.splitlines():
        line = line.strip()
        if not line or SEP not in line:
            continue
        parts = [p.strip() for p in line.split(SEP)]
        if len(parts) < 2:
            continue
        word, sentence = parts[0], parts[1]
        if not word or not sentence:
            continue

        match = targets.get(word.casefold())
        if match is None or match.keyword.text.casefold() in used:
            dropped += 1
            continue

        has_word = any(vocab.found_in(form, sentence) for form in match.keyword.forms)
        if not has_word:
            dropped += 1
            continue

        invented = vocab.matched_keys(sentence) - allowed
        if invented:
            dropped += 1
            continue

        used.add(match.keyword.text.casefold())
        hints.append(Hint(
            keyword=match.keyword.text,
            sentence=sentence,
            experiences=match.experiences,
        ))
        if len(hints) >= MAX_HINTS:
            break

    return tuple(hints), dropped


def _experiences_block(evidence: UserEvidence, report: CoverageReport) -> str:
    """프롬프트에 넣을 경험 글. **근거가 된 경험만** 넣는다.

    전부 넣으면 관계없는 경험까지 모델에 가고, 모델이 그쪽 사실을 섞는다.
    """
    needed = {label for m in report.writable_now for label in m.experiences}
    lines = [
        f"- {e.label}: {e.haystack()}"
        for e in evidence.experiences
        if e.label in needed
    ]
    return "\n".join(lines)


async def analyze(
    posting: PostingFields,
    evidence: UserEvidence,
    *,
    guard: Guardrail,
    user_id: str,
    role: str,
    session_id: str = "",
    is_test: bool = False,
    request_id: uuid.UUID | None = None,
    use_llm: bool = True,
) -> AnalyzeResult:
    """공고를 분석해 요건 대조 결과를 돌려준다."""
    prepared = prepare_posting(posting)
    found = tuple(kw_mod.extract(prepared.fields))
    report = compare(found, evidence)
    questions = questions_for(report)

    base = dict(
        keywords=found,
        report=report,
        questions=questions,
        posting_flags=prepared.flags,
        posting_truncated=prepared.truncated,
        counts=report.counts(),
    )

    writable = report.writable_now
    if not use_llm or not writable:
        # 경험에만 있는 요건이 없으면 모델이 할 일이 없다.
        # 빠진 요건에는 문장을 만들지 않는다 — 모듈 주석 참조
        return AnalyzeResult(**base)

    # ★ 가드레일에는 **템플릿이 아닌 것 전부**를 넘기고, 조립은 A8 안에서 하게 한다.
    #   조립한 글을 넘기면 A3·A12 가 우리 템플릿까지 검사 대상으로 보고, 문장 전체를
    #   보는 규칙이 죽는다 (A12 `is_continuation` 이 그래서 A10-MULTI-04 를 놓쳤다).
    #
    #   경험만 넘기지 않는 이유 — 빠진 낱말도 모델에 가는 글이다. 한쪽만 넘기면
    #   **검사와 치환에서 빠진다.** 표시로 이어 보내고 조립할 때 다시 가른다.
    guarded = _GUARD_SEP.join((
        _experiences_block(evidence, report),
        "\n".join(f"- {m.keyword.text}" for m in writable[:MAX_HINTS]),
    ))

    def build(query: str, chunks) -> LlmRequest:
        experiences, _, missing = query.partition(_GUARD_SEP)
        return LlmRequest(
            prompt=_PROMPT.format(
                sep=SEP, limit=MAX_HINTS, experiences=experiences, missing=missing
            ),
            system=DEFAULT_SYSTEM_PROMPT,
        )
    ctx = RequestContext(
        user_id=user_id, role=role, feature=FEATURE,
        session_id=session_id, is_test=is_test,
        # 감사 로그 request_id 를 HTTP X-Request-ID 와 같게 맞춘다(B16 요청).
        # 라우터가 주지 않으면(단위 테스트 등) 새로 만든다.
        request_id=request_id or uuid.uuid4(),
    )

    try:
        result = await guard.run(guarded, ctx, prompt=build)
    except LlmUnavailable:
        # 제공자 미정(2026-10). 규칙 결과만으로도 쓸 수 있어야 한다
        return AnalyzeResult(**base, llm_unavailable=True)

    if result.blocked:
        return AnalyzeResult(
            **base, llm_used=True,
            blocked_reason=result.verdict.rule_id or "차단되었습니다",
        )

    hints, dropped = parse_hints(result.text, report=report, evidence=evidence)
    return AnalyzeResult(**base, hints=hints, llm_used=True, dropped_hints=dropped)
