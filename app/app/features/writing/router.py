"""A7 — 맞춤법·문장 개선 API (tasks.md A7).

★ **저장하지 않는다.** 제안을 만들고 수락분을 반영해 돌려줄 뿐이다.
  버전 저장은 B4 경로(`resumes.service.create_version`)를 쓸 예정이고,
  `source` 값 규약을 B와 협의 중이다 (2026-10-22).

★ LLM 은 A8 가드레일만 거친다. 라우터가 모델을 직접 부르지 않는다
  (tasks.md 공통 규칙 2번, D11 이 CI 에서 막는다).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import AuthenticatedUser
from app.features.writing import service
from app.features.writing.schemas import (
    ApplyRequest,
    ApplyResponse,
    ProofreadRequest,
    ProofreadResponse,
    StarOut,
    SuggestionOut,
)
from app.features.writing.suggestions import (
    OverlappingSuggestions,
    StaleSuggestion,
    apply_suggestions,
)
from app.guardrail import Guardrail
from app.guardrail.fastapi import (
    get_guardrail,
    guardrail_kwargs,
    session_header,
)

router = APIRouter(prefix="/writing", tags=["writing"])




@router.post("/proofread", response_model=ProofreadResponse)
async def proofread(
    payload: ProofreadRequest,
    user: AuthenticatedUser,
    guard: Guardrail = Depends(get_guardrail),
    session_id: str | None = Depends(session_header),
) -> ProofreadResponse:
    """글을 검사해 고칠 곳을 돌려준다.

    1차는 규칙, 2차는 LLM 이다. STAR 요소가 2개 이하면 2차를 돌리지 않고
    무엇이 빠졌는지 안내한다 — 빈칸이 많은 글을 모델에 주면 없는 경험을 지어낸다.
    """
    result = await service.improve(
        payload.text,
        guard=guard,
        **guardrail_kwargs(user, session_id),
        use_llm=payload.use_llm,
    )

    return ProofreadResponse(
        suggestions=[SuggestionOut.of(s) for s in result.suggestions],
        star=StarOut.of(result.star),
        llm_used=result.llm_used,
        llm_unavailable=result.llm_unavailable,
        blocked_reason=result.blocked_reason,
        counts=result.counts,
    )


@router.post("/apply", response_model=ApplyResponse)
def apply(payload: ApplyRequest, user: AuthenticatedUser) -> ApplyResponse:
    """수락한 제안만 반영해 돌려준다. 저장하지 않는다.

    모델을 부르지 않으므로 동기 함수다.
    """
    suggestions = [s.to_domain() for s in payload.suggestions]

    try:
        text = apply_suggestions(payload.text, suggestions, payload.accepted)
    except StaleSuggestion as exc:
        # 제안을 받은 뒤 글을 고쳤다. 다시 검사하면 된다
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except OverlappingSuggestions as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    accepted = set(payload.accepted)
    applied = sum(1 for s in suggestions if s.id in accepted and s.is_replacement)
    return ApplyResponse(text=text, applied=applied)
