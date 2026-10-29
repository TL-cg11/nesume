"""A7 — 맞춤법·문장 개선 API (tasks.md A7).

★ **저장하지 않는다.** 제안을 만들고 수락분을 반영해 돌려줄 뿐이다.
  버전 저장은 B4 경로(`resumes.service.create_version`)를 쓸 예정이고,
  `source` 값 규약을 B와 협의 중이다 (2026-10-22).

★ LLM 은 A8 가드레일만 거친다. 라우터가 모델을 직접 부르지 않는다
  (tasks.md 공통 규칙 2번, D11 이 CI 에서 막는다).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import AuthenticatedUser, CurrentUser, require_interactive
from app.db import get_db
from app.features.profile.router import get_store as get_profile_store
from app.features.profile.store import ProfileStore
from app.features.resumes import pii_hooks
from app.features.resumes import service as resumes_service
from app.features.writing import rewrite_service, service, star_complete, star_review
from app.features.writing.rewrite import RewriteOptionError
from app.features.writing.schemas import (
    ApplyRequest,
    ApplyResponse,
    ProofreadRequest,
    ProofreadResponse,
    RewriteApplyRequest,
    RewriteApplyResponse,
    RewriteRequest,
    RewriteResponse,
    StarCompleteRequest,
    StarCompleteResponse,
    StarOut,
    StarReviewRequest,
    StarReviewResponse,
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

Db = Annotated[Session, Depends(get_db)]




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


@router.post("/star", response_model=StarReviewResponse)
async def review_star(
    payload: StarReviewRequest,
    user: AuthenticatedUser,
    guard: Guardrail = Depends(get_guardrail),
    session_id: str | None = Depends(session_header),
) -> StarReviewResponse:
    """STAR 네 요소를 모델이 판정한다(충분·부족·없음 + 근거 + 보완 질문).

    모델을 못 쓰면 규칙 판정(있다/없다)으로 내려간다. 글을 고쳐 쓰지 않는다.
    """
    result = await star_review.review(
        payload.text, guard=guard, **guardrail_kwargs(user, session_id),
    )
    return StarReviewResponse.of(result)


@router.post("/star/complete", response_model=StarCompleteResponse)
async def complete_star(
    payload: StarCompleteRequest,
    # 글을 만들어 내는 대화형 엔드포인트다. 리라이팅과 같이 시스템 계정은 막는다
    user: CurrentUser = Depends(require_interactive),
    guard: Guardrail = Depends(get_guardrail),
    session_id: str | None = Depends(session_header),
) -> StarCompleteResponse:
    """사용자가 고른 STAR 요소를 모델이 써 넣거나 다듬은 글을 돌려준다. 저장하지 않는다."""
    try:
        result = await star_complete.complete(
            payload.text, payload.fills(), list(payload.omit),
            guard=guard, **guardrail_kwargs(user, session_id),
        )
    except star_complete.StarCompleteError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from None
    return StarCompleteResponse.of(payload.text, result)


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


# --- A6 리라이팅 ---------------------------------------------------------------
#
# ★ `/rewrite` 는 만들기만 하고 저장하지 않는다. `/rewrite/apply` 가 저장한다.
#   A13(`/style/adjust` + `/style/apply`)과 같은 두 단계다 — 사용자가 **보고 고른
#   뒤에** 저장되어야 한다.


@router.post("/rewrite", response_model=RewriteResponse)
async def rewrite_selection(
    payload: RewriteRequest,
    db: Db,
    # ★ 대화형 엔드포인트다. 시스템 계정은 호출할 수 없다 —
    #   matrix.yaml 의 "system 대화형 불가" 를 D7 require_interactive 가 막는다.
    #   D7 의 독스트링이 "대화형 엔드포인트(리라이팅·면접 등)" 이라고 가리키는 자리다.
    user: CurrentUser = Depends(require_interactive),
    guard: Guardrail = Depends(get_guardrail),
    store: ProfileStore = Depends(get_profile_store),
    session_id: str | None = Depends(session_header),
) -> RewriteResponse:
    """고른 구간을 다시 쓴 후보 3개를 돌려준다. 저장하지 않는다."""
    try:
        options = payload.options()
        result = await rewrite_service.rewrite(
            db, payload.text, options,
            guard=guard, store=store, use_llm=payload.use_llm,
            style_sample=payload.style_sample,
            **guardrail_kwargs(user, session_id),
        )
    except RewriteOptionError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from None
    return RewriteResponse.of(payload.text, result)


@router.post("/rewrite/apply", response_model=RewriteApplyResponse, status_code=status.HTTP_201_CREATED)
def apply_rewrite(
    payload: RewriteApplyRequest,
    db: Db,
    # 만들기와 **같은 조건**으로 막는다. 한쪽만 막으면 나머지가 열린 길이 된다
    # (A7 /writing/apply · A13 /style/apply 와 같은 판단, PR #11).
    user: CurrentUser = Depends(require_interactive),
) -> RewriteApplyResponse:
    """고른 후보를 새 버전으로 저장한다 (B4, `source="ai"`).

    모델을 부르지 않으므로 동기 함수다.
    """
    try:
        result = rewrite_service.apply_candidate(
            db, owner_id=user.sub,
            resume_id=payload.resume_id, question_id=payload.question_id,
            body=payload.body,
        )
    except pii_hooks.SensitiveInputBlocked:
        # 안내 문구는 B4 와 같은 것을 쓴다 — 같은 저장 경로에서 같은 이유로 막혔는데
        # 화면마다 다른 말이 나오면 사용자는 다른 문제로 읽는다
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "주민번호·계좌번호 등 민감정보는 제공하지 않습니다. 입력 시에도 자동 차단됩니다.",
        ) from None
    except resumes_service.VersionLimitReached:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"문항당 버전은 {resumes_service.MAX_VERSIONS_PER_QUESTION}개까지 저장됩니다. "
            "지울 버전을 골라 삭제한 뒤 저장해 주세요.",
        ) from None

    if result is None:
        # 없는 문항과 남의 문항을 **같게** 답한다 (존재 노출 금지)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "문항을 찾을 수 없습니다.")

    version, _ = result
    return RewriteApplyResponse(version_id=version.id, char_count=len(version.body))
