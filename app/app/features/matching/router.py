"""A11 — 공고 키워드·매칭 분석 API (tasks.md A11).

★ 저장하지 않는다. 분석만 한다.
★ LLM 은 A8 가드레일만 거친다 — 라우터가 모델을 직접 부르지 않는다
  (tasks.md 공통 규칙 2번, D11 이 CI 에서 막는다).
★ 공고를 읽는 창구는 **C 가 연 `postings.read.get_posting_fields` 하나**다.
  `JobPosting` ORM 을 import 하지 않는다 (C 답변 2026-10-22).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError

from app.auth import CurrentUser, require_interactive
from app.features.matching import service
from app.features.matching.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    HintOut,
    MatchOut,
    PostingIn,
)
from app.guardrail import Guardrail
from app.guardrail.fastapi import (
    get_guardrail,
    guardrail_kwargs,
    session_header,
)

router = APIRouter(prefix="/matching", tags=["matching"])

#: 공고 한 건을 읽는 함수. 없으면 None.
#: (공고 id, 호출자 user_id) → 공고 필드. 볼 권한이 없으면 None.
PostingLookup = Callable[[uuid.UUID, str], dict[str, str | None] | None]


def read_posting_fields(posting_id: uuid.UUID, user_id: str) -> dict[str, str | None] | None:
    """C4 창구를 **짧은 세션**으로 호출한다.

    ★ ``user_id`` 는 C 창구가 **키워드 전용·필수**로 요구한다 — 신원 없이 부를 수 없다
      (fail-closed). 비공개 공고(``source='user'``)는 소유자 본인일 때만 돌아온다.

    ★ 다른 라우터처럼 ``Depends(get_db)`` 를 쓰지 않는 이유가 있다.
      이 엔드포인트는 LLM 을 불러 **응답이 최대 30초**다. 요청 단위 세션을 받으면
      모델을 기다리는 동안 커넥션 풀의 자리를 계속 잡고 있는다. 공고 조회는
      모델 호출 **전에 끝나는 읽기 한 번**이라, 읽고 바로 닫는 쪽이 맞다.
      (@D — 이 판단이 운영 설정과 어긋나면 알려주십시오.)

    ★ import 를 함수 안에서 한다. 모듈 수준에서 하면 A11 패키지가 DB 드라이버·설정을
      요구하게 되어 단위 테스트가 DB 없이 돌지 못한다 (A8 이 `app.models` 를
      import 하지 않는 것과 같은 이유). 또 C 브랜치가 머지되기 전에도 import 가 된다.
    """
    from app.db import SessionLocal
    from app.postings.read import get_posting_fields

    with SessionLocal() as session:
        return get_posting_fields(session, posting_id, user_id=user_id)


def get_posting_lookup() -> PostingLookup:
    """테스트에서 갈아끼울 수 있게 의존성으로 뺀다."""
    return read_posting_fields




def _posting_from(
    payload: AnalyzeRequest, lookup: PostingLookup, user_id: str
) -> PostingIn:
    """요청에서 공고를 꺼낸다. `posting_id` 면 C4 창구로 읽는다."""
    if payload.posting is not None:
        return payload.posting

    # ★ 권한 검사는 **C 창구 안에서** 한다 (2026-10-23 C 보안 패치).
    #   비공개 공고(`source='user'`)는 소유자 본인이 아니면 None 이 돌아온다.
    #   여기서 `owner_user_id` 를 직접 보면 조회 경로를 하나로 모은 합의가 깨진다.
    #
    #   없는 공고와 **볼 권한이 없는 공고를 똑같이 404** 로 답한다 — 403 으로 구분하면
    #   "그 UUID 의 공고는 있다"는 사실이 새어 나간다.
    fields = lookup(payload.posting_id, user_id)  # type: ignore[arg-type]
    if fields is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "공고를 찾을 수 없습니다")

    try:
        return PostingIn(**fields)
    except ValidationError as exc:
        # 분석할 본문·요건이 전부 비어 있는 공고다. 식별이 불확실한 검토대상 공고
        # (`needs_review`)에서 실제로 일어난다 — C 창구가 그런 공고도 돌려준다.
        # 500 으로 흘리면 사용자는 고장으로 본다
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "이 공고에는 분석할 본문·요건이 없습니다",
        ) from exc


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    payload: AnalyzeRequest,
    user: CurrentUser = Depends(require_interactive),
    guard: Guardrail = Depends(get_guardrail),
    session_id: str | None = Depends(session_header),
    lookup: PostingLookup = Depends(get_posting_lookup),
) -> AnalyzeResponse:
    """공고 요건을 뽑아 자소서·경험과 대조한다.

    빠진 요건에는 **문장을 제안하지 않고 질문을 돌려준다.** 경험엔 있는데 자소서에
    안 쓴 요건만 문장을 만든다 — 지어낼 필요가 없는 쪽이다.
    """
    posting = _posting_from(payload, lookup, user.sub)

    result = await service.analyze(
        posting.to_domain(),
        payload.evidence(),
        guard=guard,
        **guardrail_kwargs(user, session_id),
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
