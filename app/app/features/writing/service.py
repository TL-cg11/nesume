"""A7 조립 — 1차(규칙) + 2차(LLM).

흐름은 이렇다.

    1. 규칙 검사 (proofread.check)        LLM 없이, 항상 같은 결과
    2. STAR 분석 (star.analyze)
    3. 요소가 2개 이하면  → 보완 안내만 하고 **여기서 끝낸다**
    4. 아니면 LLM 2차      → A8 가드레일 파이프라인 경유
    5. 모델 제안을 **원문과 대조해 검증**한 뒤 합친다

★ LLM 을 직접 부르지 않는다. A8 만 호출한다 (tasks.md 공통 규칙 2번).
  그래서 PII 토큰화·질의 분류·출력 검사·감사 로그가 전부 자동으로 걸린다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.features.writing import proofread, star
from app.features.writing.star import StarAnalysis
from app.features.writing.suggestions import Suggestion
from app.guardrail import Guardrail, LlmUnavailable, RequestContext

FEATURE = "writing.proofread"

#: 모델 제안 한 줄의 구분자. 흔한 기호(|, 탭, 쉼표)는 본문에 섞이므로 피한다.
SEP = "|||"

#: 모델에게 받을 제안의 최대 개수. 상한이 없으면 모델이 문장마다 참견한다.
MAX_LLM_SUGGESTIONS = 8

_PROMPT = """다음 자기소개서 문장을 더 읽기 좋게 고칠 곳을 찾아 주십시오.

규칙:
- 사실을 바꾸거나 없는 경험을 만들지 않습니다.
- 고칠 곳이 없으면 아무것도 쓰지 않습니다.
- 한 줄에 하나씩, 아래 형식으로만 씁니다. 다른 설명은 쓰지 않습니다.

형식:  원문{sep}고친문장{sep}이유

원문은 아래 글에 **그대로 있는 조각**이어야 합니다. 최대 {limit}개까지만 씁니다.

--- 글 ---
{text}"""


@dataclass(frozen=True)
class ImproveResult:
    """교정 결과.

    ★ 이 객체를 로그에 쓰지 않는다. 제안에는 원문 조각이 들어 있다.
      감사 로그에는 가드레일이 남긴 것(개수·판정)만 남는다.
    """

    suggestions: list[Suggestion]
    star: StarAnalysis
    #: LLM 2차를 돌렸는가. STAR 요소가 적으면 돌리지 않는다
    llm_used: bool = False
    #: 가드레일 판정이 차단이면 이유가 담긴다
    blocked_reason: str | None = None
    #: 모델 제공자가 아직 설정되지 않아 2차를 건너뛰었는가.
    #: 제공자 확정 전까지는 1차 결과만으로도 쓸 수 있어야 한다
    llm_unavailable: bool = False
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def rule_suggestions(self) -> list[Suggestion]:
        return [s for s in self.suggestions if s.source == "rule"]

    @property
    def llm_suggestions(self) -> list[Suggestion]:
        return [s for s in self.suggestions if s.source == "llm"]


def _counts(suggestions: list[Suggestion]) -> dict[str, int]:
    out: dict[str, int] = {}
    for s in suggestions:
        out[s.rule_id] = out.get(s.rule_id, 0) + 1
    return out


def parse_llm_suggestions(reply: str, text: str, *, taken: list[Suggestion]) -> list[Suggestion]:
    """모델 응답을 제안 목록으로 바꾼다.

    ★ **원문과 대조해 검증한다.** 모델이 "이 문장을 고치세요"라고 했는데 그 문장이
      글에 없으면 버린다. 검증 없이 적용하면 글에 없던 문장이 바뀐 것처럼 보이거나,
      엉뚱한 자리가 덮어써진다.

    겹치는 자리는 **규칙 제안을 우선**한다. 규칙 쪽이 근거가 분명하기 때문이다.
    단, 안내만 하는 규칙 제안(상투어·긴 문장)과는 겹쳐도 된다 — 그쪽은 글을 바꾸지 않아
    충돌이 아니고, 오히려 "구체적으로 쓰라"는 안내에 모델의 구체적 대안이 따라붙는
    것이 사용자에게 가장 쓸모 있다.
    """
    out: list[Suggestion] = []
    blocked = [(s.start, s.end) for s in taken if s.is_replacement]

    for line in reply.splitlines():
        line = line.strip()
        if not line or SEP not in line:
            continue

        parts = [p.strip() for p in line.split(SEP)]
        if len(parts) < 2:
            continue
        original, suggested = parts[0], parts[1]
        reason = parts[2] if len(parts) > 2 else "문장을 다듬었습니다"

        if not original or original == suggested:
            continue

        start = text.find(original)
        if start < 0:
            continue  # ★ 글에 없는 조각 — 버린다
        end = start + len(original)

        if any(start < b_end and b_start < end for b_start, b_end in blocked):
            continue  # 규칙 제안과 겹친다

        out.append(Suggestion(
            kind="style", rule_id="WR_LLM_STYLE",  # type: ignore[arg-type]
            start=start, end=end,
            original=original, suggested=suggested,
            reason=reason, source="llm",
            # 모델 제안은 근거를 댈 수 없다. 규칙 제안과 같은 무게로 보여주면
            # 사용자가 구분 없이 수락하게 된다
            confidence="medium",
        ))
        blocked.append((start, end))

        if len(out) >= MAX_LLM_SUGGESTIONS:
            break

    return out


async def improve(
    text: str,
    *,
    guard: Guardrail,
    user_id: str,
    role: str,
    session_id: str = "",
    is_test: bool = False,
    use_llm: bool = True,
) -> ImproveResult:
    """1차 + 2차를 돌려 제안 목록을 만든다."""
    rule_found = proofread.check(text)
    analysis = star.analyze(text)

    # STAR 요소가 적으면 변환을 맡기지 않는다. 모델이 없는 내용을 지어낸다
    if not analysis.can_convert:
        found = rule_found + star.guidance(analysis, text)
        found.sort(key=lambda s: (s.start, s.end, s.rule_id))
        return ImproveResult(suggestions=found, star=analysis, counts=_counts(found))

    if not use_llm:
        return ImproveResult(suggestions=rule_found, star=analysis, counts=_counts(rule_found))

    ctx = RequestContext(
        user_id=user_id, role=role, feature=FEATURE,
        session_id=session_id, is_test=is_test,
    )
    try:
        result = await guard.run(
            _PROMPT.format(sep=SEP, limit=MAX_LLM_SUGGESTIONS, text=text), ctx
        )
    except LlmUnavailable:
        # 제공자 미정(2026-10 현재). 1차 결과만 돌려준다 — 사용자가 빈손으로 끝나지 않는다
        return ImproveResult(
            suggestions=rule_found, star=analysis,
            llm_unavailable=True, counts=_counts(rule_found),
        )

    if result.blocked:
        return ImproveResult(
            suggestions=rule_found, star=analysis, llm_used=True,
            blocked_reason=result.verdict.rule_id or "차단되었습니다",
            counts=_counts(rule_found),
        )

    llm_found = parse_llm_suggestions(result.text, text, taken=rule_found)
    found = rule_found + llm_found
    found.sort(key=lambda s: (s.start, s.end, s.rule_id))

    return ImproveResult(
        suggestions=found, star=analysis, llm_used=True, counts=_counts(found)
    )
