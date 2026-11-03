"""A13 — 글자 수·문체 조정 API (tasks.md A13).

★ 저장하지 않는다. 측정·제안·다시쓰기까지만 한다.
★ LLM 은 A8 가드레일만 거친다 (tasks.md 공통 규칙 2번, D11 이 CI 에서 막는다).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import CurrentUser, require_interactive
from app.features.style import service
from app.features.style.counter import TokenizedTextError, count
from app.features.style.length import OverlappingTrims, StaleTrim, apply_trims
from app.features.style.schemas import (
    AdjustRequest,
    AdjustResponse,
    ApplyRequest,
    ApplyResponse,
    CountOut,
)
from app.guardrail import Guardrail
from app.guardrail.fastapi import (
    get_guardrail,
    guardrail_kwargs,
    session_header,
)

router = APIRouter(prefix="/style", tags=["style"])




@router.post("/adjust", response_model=AdjustResponse)
async def adjust(
    payload: AdjustRequest,
    user: CurrentUser = Depends(require_interactive),
    guard: Guardrail = Depends(get_guardrail),
    session_id: str | None = Depends(session_header),
) -> AdjustResponse:
    """글자 수와 문체를 본다. 규칙으로 못 줄이면 모델에게 다시 쓰게 한다.

    ★ 모델 결과는 **서버가 다시 세고 다시 판정한 뒤**에만 돌려준다. 모델은 글자 수를
      세지 못한다 — 맞지도 않는 글을 "줄였습니다" 로 내보내면 사용자는 저장 단계에서
      거절당한다.
    """
    try:
        result = await service.adjust(
            payload.text,
            guard=guard,
            **guardrail_kwargs(user, session_id),
            limit=payload.limit,
            min_chars=payload.min_chars,
            target_tone=payload.target_tone,  # type: ignore[arg-type]
            use_llm=payload.use_llm,
        )
    except TokenizedTextError as exc:
        # 저장된 본문(토큰화 상태)을 보냈다. 조용히 세면 저장될 수와 다른 수를 보여준다
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    return AdjustResponse.of(result, notice=service.NO_INVENTION_NOTICE)


@router.post("/apply", response_model=ApplyResponse)
def apply(
    payload: ApplyRequest,
    user: CurrentUser = Depends(require_interactive),
) -> ApplyResponse:
    """수락한 제안만 반영해 돌려준다. 저장하지 않는다.

    모델을 부르지 않으므로 동기 함수다.
    """
    trims = [t.to_domain() for t in payload.trims]
    try:
        text = apply_trims(payload.text, trims, set(payload.accepted))
    except StaleTrim as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except OverlappingTrims as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    accepted = set(payload.accepted)
    return ApplyResponse(
        text=text,
        applied=sum(1 for t in trims if t.id in accepted),
        count=CountOut.of(count(text, allow_tokens=True)),
    )
