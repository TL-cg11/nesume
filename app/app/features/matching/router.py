"""A11 — 공고 키워드·매칭 분석 API (tasks.md A11).

★ 저장하지 않는다. 분석만 한다.
★ LLM 은 A8 가드레일만 거친다 — 라우터가 모델을 직접 부르지 않는다
  (tasks.md 공통 규칙 2번, D11 이 CI 에서 막는다).
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends

from app.auth import AuthenticatedUser
from app.features.matching import service
from app.features.matching.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    HintOut,
    MatchOut,
)
from app.guardrail import Guardrail

router = APIRouter(prefix="/matching", tags=["matching"])


@lru_cache(maxsize=1)
def _default_guardrail() -> Guardrail:
    """앱 전체가 공유하는 가드레일. 요청마다 새로 만들지 않는다.

    제공자·검색·감사 로그 주입 지점은 아직 정해지지 않아 기본값이다.
    제공자가 없으면 규칙 결과만 돌려준다 (`service.analyze` 참조).
    """
    return Guardrail()


def get_guardrail() -> Guardrail:
    """테스트에서 갈아끼울 수 있게 의존성으로 뺀다."""
    return _default_guardrail()


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    payload: AnalyzeRequest,
    user: AuthenticatedUser,
    guard: Guardrail = Depends(get_guardrail),
) -> AnalyzeResponse:
    """공고 요건을 뽑아 자소서·경험과 대조한다.

    빠진 요건에는 **문장을 제안하지 않고 질문을 돌려준다.** 경험엔 있는데 자소서에
    안 쓴 요건만 문장을 만든다 — 지어낼 필요가 없는 쪽이다.
    """
    result = await service.analyze(
        payload.posting.to_domain(),
        payload.evidence(),
        guard=guard,
        user_id=user.sub,
        role=str(user.role),
        use_llm=payload.use_llm,
    )

    return AnalyzeResponse(
        matches=[MatchOut.of(m) for m in result.report.matches],
        questions=list(result.questions),
        notice=service.NO_INVENTION_NOTICE,
        hints=[HintOut.of(h) for h in result.hints],
        counts=result.counts,
        required_rate=result.report.required_rate,
        rate_reliable=result.report.rate_reliable,
        posting_flags=list(result.posting_flags),
        posting_truncated=result.posting_truncated,
        llm_used=result.llm_used,
        llm_unavailable=result.llm_unavailable,
        blocked_reason=result.blocked_reason,
        dropped_hints=result.dropped_hints,
    )
