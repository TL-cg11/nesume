"""A13 조립 — 글자 수·문체 조정.

    1. 세기        counter.count          B4 와 같은 기준
    2. 문체 판정    tone.analyze           혼용 탐지
    3. 규칙 줄이기  length.find_trims      LLM 없이
    4. 그래도 넘치면 → 모델에게 다시 쓰게 한다 (A8 경유)
    5. **검증**     길이·문체·숫자를 서버가 다시 본다

★ LLM 을 직접 부르지 않는다. A8 만 호출한다 (tasks.md 공통 규칙 2번).

## ★ 모델은 글자 수를 세지 못한다

"900자로 줄여라" 는 모델이 가장 자주 틀리는 지시다. 토큰 단위로 생성하므로
**글자를 셀 수가 없다.** 그래서 이 모듈은 모델 응답을 받으면 **서버가 다시 센다.**

맞지 않으면 한 번 더 요청하고(`MAX_REWRITE_ATTEMPTS`), 그래도 안 맞으면 **버린다.**
맞지도 않는 글을 "줄였습니다" 라고 내보내면 사용자는 **저장 단계에서 거절당한다.**

## ★ 새로 생긴 숫자가 있으면 버린다

자소서에서 가장 위험한 환각은 **성과 수치**다.

    원문: 응답시간을 40% 단축했습니다
    모델: 응답시간을 60% 단축해 비용 1,200만원을 절감했습니다
                     ^^^            ^^^^^^^ 원문에 없다 → 전체를 버린다

다시 쓰기는 글 전체가 바뀌므로 **일부만 믿을 수 없다.** 하나라도 새 숫자가 나오면
그 응답을 통째로 버리고 규칙 결과만 돌려준다.

## ★ 모자란 분량은 채워 주지 않는다

최소 글자 수에 미치면 **질문만** 돌려준다. 분량을 모델에게 채우게 하면
**없는 경험을 지어낸다** — A7(STAR)·A11(빠진 요건)과 같은 판단이다.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field, replace

from app.features.style import length
from app.features.style import tone as tone_mod
from app.features.style.counter import CharCount, count
from app.features.style.length import Trim
from app.features.style.tone import DEFAULT_TONE, TONE_NAMES, Tone, ToneAnalysis
from app.guardrail import Guardrail, LlmUnavailable, RequestContext

FEATURE = "style.adjust"

#: 모델에게 다시 쓰게 하는 최대 횟수. 길이가 안 맞으면 한 번 더 부른다.
#: 상한이 없으면 모델이 못 맞추는 글에서 호출이 계속 늘어난다 (A2 상한은 4회).
MAX_REWRITE_ATTEMPTS = 2

#: 숫자로 볼 모양. 1,200 · 40 · 3.5 를 한 덩어리로 본다.
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")

#: 모델이 붙이기 쉬운 머리말. 길이 검사를 통과하려면 떼야 한다.
_PREAMBLE = re.compile(r"^\s*(?:다음과\s*같이|아래와\s*같이)[^\n:]*[:：]\s*", re.I)

#: 분량이 모자랄 때 돌려주는 질문. **문장을 만들어 주지 않는다.**
SHORT_QUESTIONS: tuple[str, ...] = (
    "결과를 숫자로 적을 수 있습니까? (예: 응답시간 40% 단축, 참여 인원 12명)",
    "그 일에서 **본인이** 한 행동은 무엇이었습니까? 팀이 한 일과 구분해 적어 보십시오.",
    "그 경험에서 무엇을 배웠고, 지원하는 일과 어떻게 이어집니까?",
)

NO_INVENTION_NOTICE = (
    "분량을 채우려고 없는 경험을 쓰지 않는 것이 맞습니다. 없는 경험은 면접에서 드러납니다."
)

_PROMPT = """다음 자기소개서 문항 답변을 조건에 맞게 **다시 써** 주십시오.

조건:
- 글자 수: **{limit}자 이하** (공백 포함). 지금은 {current}자입니다.
- 문체: **{tone_name}**로 통일합니다.
- **사실을 바꾸거나 더하지 않습니다.** 숫자·기간·기관명을 새로 만들지 않습니다.
- 내용을 줄여야 하면 **덜 중요한 설명**을 줄이고, 경험과 결과는 남깁니다.

출력 형식: **다시 쓴 본문만** 씁니다. 설명·머리말·따옴표를 붙이지 않습니다.

--- 본문 ---
{text}"""


@dataclass(frozen=True)
class Rewrite:
    """검증을 통과한 다시 쓴 글."""

    text: str
    count: CharCount
    tone: Tone | None
    #: 모델이 근거를 댈 수 없다. 화면에서 "확인 필요"로 표시한다
    confidence: str = "medium"


@dataclass(frozen=True)
class AdjustResult:
    #: 받은 글 그대로의 측정값
    count: CharCount
    tone: ToneAnalysis
    target_limit: int | None
    target_tone: Tone
    #: 규칙으로 줄일 수 있는 자리
    trims: tuple[Trim, ...] = ()
    #: 규칙 제안을 **전부** 수락했을 때의 글자 수 (미리보기)
    rule_count: CharCount | None = None
    #: 모델이 다시 쓴 글. 검증을 통과한 것만 담긴다
    rewrite: Rewrite | None = None
    #: 모델 결과를 버린 이유. 사용자에게 그대로 보여준다
    rejected_reason: str | None = None
    #: 분량이 모자랄 때의 질문
    questions: tuple[str, ...] = ()
    attempts: int = 0
    llm_used: bool = False
    llm_unavailable: bool = False
    blocked_reason: str | None = None
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def fits(self) -> bool:
        """지금 글이 제한을 지키는가."""
        return self.count.fits(self.target_limit)

    @property
    def rule_only_fits(self) -> bool:
        """규칙 제안만 수락해도 제한을 지키는가 — 모델을 부를 필요가 없는 경우다."""
        return self.rule_count is not None and self.rule_count.fits(self.target_limit)


def numbers_in(text: str) -> set[str]:
    """글에 쓰인 숫자. 자리수 구분 쉼표는 지우고 본다 (1,200 과 1200 은 같다)."""
    return {m.group().replace(",", "") for m in _NUMBER.finditer(text)}


def invented_numbers(original: str, rewritten: str) -> set[str]:
    """다시 쓴 글에만 있는 숫자. 비어 있지 않으면 **지어낸 것**이다."""
    return numbers_in(rewritten) - numbers_in(original)


def clean_reply(reply: str) -> str:
    """모델 응답에서 머리말·따옴표를 떼낸다.

    형식을 지키라고 적어도 "다음과 같이 줄였습니다:" 가 붙어 온다. 그대로 세면
    길이 검사에서 떨어지는데, 떨어진 이유가 **본문이 길어서가 아니다.**
    """
    out = _PREAMBLE.sub("", reply).strip()
    if len(out) >= 2 and out[0] in "\"'“”「『" and out[-1] in "\"'“”」』":
        out = out[1:-1].strip()
    return out


def verify_rewrite(
    original: str,
    reply: str,
    *,
    limit: int | None,
    target_tone: Tone,
) -> tuple[Rewrite | None, str | None]:
    """모델이 다시 쓴 글을 검사한다. 통과하면 `(Rewrite, None)`, 아니면 `(None, 이유)`.

    검사 순서는 **버려야 할 이유가 무거운 것부터**다 — 사용자에게 보여줄 이유가
    하나뿐이라, 숫자를 지어낸 것이 "조금 길다"보다 먼저 와야 한다.
    """
    text = clean_reply(reply)
    if not text:
        return None, "모델이 빈 응답을 돌려주었습니다"
    if text == original.strip():
        return None, "모델이 글을 바꾸지 않았습니다"

    invented = invented_numbers(original, text)
    if invented:
        # ★ 일부만 믿을 수 없다. 다시 쓰기는 글 전체가 바뀐다
        shown = ", ".join(sorted(invented)[:3])
        return None, f"원문에 없는 숫자가 들어가 버렸습니다 ({shown})"

    measured = count(text, allow_tokens=True)
    if not measured.fits(limit):
        return None, f"{measured.total}자로 줄어들어 아직 {measured.over_by(limit)}자 넘습니다"

    analysis = tone_mod.analyze(text)
    off = analysis.off_tone(target_tone)
    if off:
        return None, (
            f"{TONE_NAMES[target_tone]}가 아닌 문장이 {len(off)}개 남았습니다"
        )

    return Rewrite(text=text, count=measured, tone=analysis.main), None


async def adjust(
    text: str,
    *,
    guard: Guardrail,
    user_id: str,
    role: str,
    limit: int | None = None,
    min_chars: int | None = None,
    target_tone: Tone = DEFAULT_TONE,
    session_id: str = "",
    is_test: bool = False,
    request_id: uuid.UUID | None = None,
    use_llm: bool = True,
) -> AdjustResult:
    """글자 수와 문체를 맞춘다."""
    measured = count(text)
    analysis = tone_mod.analyze(text)
    trims = tuple(length.find_trims(text))
    after_rules = length.apply_trims(text, trims, {t.id for t in trims})
    rule_count = count(after_rules, allow_tokens=True)

    counts = {
        "trims": len(trims),
        "rule_savings": length.savings(trims),
        "off_tone": len(analysis.off_tone(target_tone)),
    }
    base = dict(
        count=measured, tone=analysis,
        target_limit=limit, target_tone=target_tone,
        trims=trims, rule_count=rule_count, counts=counts,
    )

    # 분량이 모자라면 질문만 돌려준다 — 채워 주면 없는 경험을 지어낸다
    if min_chars is not None and measured.total < min_chars:
        return AdjustResult(**base, questions=SHORT_QUESTIONS)

    needs_rewrite = not rule_count.fits(limit) or bool(analysis.off_tone(target_tone))
    if not use_llm or not needs_rewrite:
        # 규칙만으로 제한과 문체를 맞췄으면 모델을 부를 이유가 없다
        return AdjustResult(**base)

    ctx = RequestContext(
        user_id=user_id, role=role, feature=FEATURE,
        session_id=session_id, is_test=is_test,
        # 감사 로그 request_id 를 HTTP X-Request-ID 와 같게 맞춘다(B16 요청).
        # 라우터가 주지 않으면(단위 테스트 등) 새로 만든다.
        request_id=request_id or uuid.uuid4(),
    )

    source = after_rules
    attempts = 0
    reason: str | None = None

    while attempts < MAX_REWRITE_ATTEMPTS:
        attempts += 1
        if attempts > 1:
            # ★ 감사 로그 PK 가 request_id 다. 같은 값으로 두 번째 시도를 남기면
            #   UniqueViolation → AuditWriteFailed 로 요청 전체가 500 이 된다(실모델로 확인).
            #   첫 시도만 HTTP X-Request-ID 와 이어지고, 재시도는 새 ID 를 쓴다
            ctx = replace(ctx, request_id=uuid.uuid4())
        prompt = _PROMPT.format(
            limit=limit if limit is not None else "제한 없음",
            current=count(source, allow_tokens=True).total,
            tone_name=TONE_NAMES[target_tone],
            text=source,
        )
        try:
            result = await guard.run(prompt, ctx)
        except LlmUnavailable:
            # 제공자 미정(2026-10). 규칙 결과만으로도 쓸 수 있어야 한다
            return AdjustResult(**base, llm_unavailable=True, attempts=attempts - 1)

        if result.blocked:
            return AdjustResult(
                **base, llm_used=True, attempts=attempts,
                blocked_reason=result.verdict.rule_id or "차단되었습니다",
            )

        rewrite, reason = verify_rewrite(
            text, result.text, limit=limit, target_tone=target_tone
        )
        if rewrite is not None:
            return AdjustResult(**base, rewrite=rewrite, llm_used=True, attempts=attempts)

        # 숫자를 지어낸 응답은 다시 물어도 같은 사실을 또 만든다. 바로 끝낸다
        if "숫자" in (reason or ""):
            break

    return AdjustResult(**base, llm_used=True, attempts=attempts, rejected_reason=reason)
