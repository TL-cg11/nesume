"""C8 — 공고 추천 API (tasks.md C8).

저장하지 않는다. 사용자 보유 역량·필터를 받아 맞춤 공고를 돌려줄 뿐이다.
LLM 직접 호출 없음(벡터 검색 + 규칙 키워드 매칭). main.py 등록은 D PR(features/__init__.py 규칙).

보유 역량(`held_keys`)은 **요청으로 받는다** — B 경험·스킬을 C가 직접 읽지 않는 단일 조회 경로
합의(docs/C8.md). 개인 벡터가 없으면 콜드스타트 안내를 돌려준다(스킬태그 임베딩 폴백은 D 서빙 후).
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import AuthenticatedUser
from app.db import get_db
from app.features.recommend import service
from app.features.recommend.schemas import (
    PostingBrief,
    RecommendationOut,
    RecommendRequest,
    RecommendResponse,
)
from app.postings.read import get_posting_fields, get_posting_link, get_recruit_fields

router = APIRouter(prefix="/recommendations", tags=["recommendations"])
Db = Annotated[Session, Depends(get_db)]

#: 콜드스타트(개인 벡터 없음) 안내.
_COLD_START_NOTICE = "자소서·경험을 등록하면 더 정확하게 추천해 드려요."


@router.post("", response_model=RecommendResponse)
def recommend(payload: RecommendRequest, user: AuthenticatedUser, db: Db):
    """맞춤 공고 추천. 개인 벡터가 없으면 cold_start=true + 안내(items 빈 목록)."""
    held_keys = list(payload.held_keys)
    if payload.resume_id is not None:
        from app.features.skill_gap.evidence import gather_evidence, held_keys_of

        evidence = gather_evidence(db, owner_id=user.sub, resume_id=payload.resume_id)
        if evidence is None:  # 없음/남의 자소서 구분 안 함
            raise HTTPException(status.HTTP_404_NOT_FOUND, "자소서를 찾을 수 없습니다")
        held_keys = sorted(set(held_keys) | set(held_keys_of(evidence)))
    recs = service.recommend(
        db,
        user_id=user.sub,
        held_keys=held_keys,
        resume_id=payload.resume_id,
        region_codes=payload.region_codes or None,
        job_codes=payload.job_codes or None,
        top_k=payload.top_k,
    )
    if not recs:
        return RecommendResponse(items=[], cold_start=True, notice=_COLD_START_NOTICE)

    items: list[RecommendationOut] = []
    for r in recs:
        fields = get_posting_fields(db, r.posting_id, user_id=user.sub)
        link = get_posting_link(db, r.posting_id, user_id=user.sub) if fields else None
        brief = (
            PostingBrief(
                title=fields["title"],
                job_name=fields["job_name"],
                company_name=link["company_name"] if link else None,
                source=link["source"] if link else None,
                url=link["source_url"] if link else None,
                field_names=[
                    f.get("name") or f"분야 {i + 1}"
                    for i, f in enumerate(get_recruit_fields(db, r.posting_id, user_id=user.sub))
                ],
            )
            if fields
            else None
        )
        items.append(
            RecommendationOut(
                posting_id=r.posting_id,
                score=r.final_score,
                vector_score=r.vector_score,
                keyword_score=r.keyword_score,
                matched_keywords=list(r.matched_keywords),
                keyword_available=r.keyword_available,
                field_index=r.field_index,
                posting=brief,
            )
        )
    return RecommendResponse(items=items, cold_start=False)
