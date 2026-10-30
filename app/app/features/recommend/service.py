"""C8 — 공고 추천 오케스트레이터 (DB·A11·검색 배선).

순수 재정렬(`rerank.py`) 위에 **멀티벡터 쿼리 → C6 검색 → 공고 집계 → 키워드 매칭 → 재정렬**을 엮는다.
실행은 통합 단계(D 임베딩 서빙·B 마이그레이션·A11 머지) — 로컬 venv로는 못 돌린다(C4 collect와 같은 결).

접근 경계:
- 쿼리 벡터 = **사용자 본인 개인 인덱스**(UserProfileEmbedding, C 소유 모델). 이미 임베딩돼 있어
  추천 시 추가 임베딩 불필요(콜드스타트만 스킬태그 임베딩 — 호출측이 `query_vectors`로 주입).
- 공고 글은 **C 창구 `get_posting_fields`로만** 읽는다(권한 검사 포함).
- 보유 역량(`held_keys`)은 **호출측이 조립해 넘긴다** — C가 B의 경험·스킬 테이블을 직접 읽으면
  단일 조회 경로 합의가 깨진다(A11 analyze가 경험을 요청으로 받는 것과 같은 이유).
"""
from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import replace

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.features.recommend.rerank import (
    DEFAULT_CANDIDATES,
    DEFAULT_TOP_K,
    KeywordMatch,
    Recommendation,
    aggregate_candidates,
    keyword_match_rate,
    rerank,
)
from app.models.embedding import MODEL_VERSION, JobPostingEmbedding, UserProfileEmbedding
from app.postings.read import get_posting_fields, get_recruit_fields, narrow_to_field

#: 공고 dict → 요구 역량 키 목록. 기본 구현은 A11을 **지연 import**(미머지 브랜치에서 import 깨짐 방지).
RequiredExtractor = Callable[[dict[str, str | None]], list[str]]


def _a11_required_keys(fields: dict[str, str | None]) -> list[str]:
    """A11 규칙 추출기로 공고 요구 역량 키를 뽑는다(통합 seam). **사전 기술만**(`category != "other"`).

    `other`는 사전 밖 문장 조각(병역·학력·경력 연수 등)이라 사용자 보유 키(사전 키만 나옴)와
    **구조적으로 일치할 수 없다** → 분모만 키워 키워드율이 늘 낮았다(docs/C8.md 키워드 점수 보정).
    """
    from app.features.matching import PostingFields, extract  # 지연 import

    allowed = {f.name for f in PostingFields.__dataclass_fields__.values()}
    found = extract(PostingFields(**{k: v for k, v in fields.items() if k in allowed}))
    return [kw.key for kw in found if kw.category != "other"]


def gather_query_vectors(
    session: Session, user_id: str, resume_id: uuid.UUID | None = None
) -> list[list[float]]:
    """멀티벡터 쿼리 소스 = 사용자 본인 자소서·경험 임베딩(삭제·버전 제외).

    `resume_id`를 주면 **그 자소서 + 그 자소서 문항에 끌어온 경험**의 청크만(본인 소유 조건은 그대로) —
    자소서별 추천. 끌어온 경험이 없으면 자소서만(2026-10-30 결정, 키워드 근거와 같은 범위).
    """
    stmt = (
        select(UserProfileEmbedding.embedding)
        .where(UserProfileEmbedding.owner_id == user_id)
        .where(UserProfileEmbedding.deleted_at.is_(None))
        .where(UserProfileEmbedding.model_version == MODEL_VERSION)
    )
    if resume_id is not None:
        from app.features.experiences.reader import linked_experiences_for_resume

        exp_ids = [e["id"] for e in linked_experiences_for_resume(session, user_id, resume_id)]
        kind, sid = UserProfileEmbedding.source_type, UserProfileEmbedding.source_id
        stmt = stmt.where(
            or_(
                and_(kind == "resume", sid == resume_id),
                and_(kind == "experience", sid.in_(exp_ids)),
            )
        )
    rows = session.execute(stmt).all()
    return [row[0] for row in rows]


def recommend(
    session: Session,
    *,
    user_id: str,
    held_keys: Iterable[str],
    region_codes: list[str] | None = None,
    job_codes: list[str] | None = None,
    top_k: int = DEFAULT_TOP_K,
    candidates: int = DEFAULT_CANDIDATES,
    query_vectors: Sequence[Sequence[float]] | None = None,
    required_extractor: RequiredExtractor | None = None,
    resume_id: uuid.UUID | None = None,
) -> list[Recommendation]:
    """맞춤 공고 상위 top_k. 개인 벡터가 없으면 콜드스타트([]) — 호출측이 스킬태그 폴백·안내.

    `query_vectors` 주입 시 그걸 쿼리로(콜드스타트 스킬태그 임베딩 등), 아니면 본인 개인 벡터를 읽는다.
    `held_keys`는 호출측이 조립(경험·스킬·자소서 역량 키). `required_extractor` 미지정 시 A11 사용.
    """
    # C6가 지역·직무 필터를 WHERE로 거는 건 사전 필터라 import만 지연 — 순수 테스트 시 미사용.
    from app.retrieval.search import search_public

    if query_vectors is not None:
        vectors = list(query_vectors)
    else:
        vectors = gather_query_vectors(session, user_id, resume_id)
    if not vectors:
        return []  # 콜드스타트: 개인 벡터 없음 → 호출측 폴백(스킬태그 쿼리 주입 또는 인기·최신)

    # ① 멀티벡터 검색 → ② 공고 집계(최고 유사도)
    rows: list[tuple[uuid.UUID, float]] = []
    for vec in vectors:
        for r in search_public(
            session, list(vec), region_codes=region_codes, job_codes=job_codes, top_k=candidates
        ):
            rows.append((r.source_id, r.distance, r.chunk_index))
    cands = aggregate_candidates(rows)
    cands.sort(key=lambda c: c.vector_score, reverse=True)
    cands = cands[:candidates]

    # ③ 공고별 키워드 매칭률(요구 역량 ∩ 보유 역량) — 공고 글은 C 창구로만(권한 포함).
    #    모집분야가 여럿이면 **가장 가까운 분야(=자소서에 맞는 분야)의 글로만** 센다(docs/C4.md 모집분야).
    extract_required = required_extractor or _a11_required_keys
    held = list(held_keys)
    chunks = _chunk_counts(session, [c.posting_id for c in cands])
    keyword_by_posting: dict[uuid.UUID, KeywordMatch] = {}
    field_by_posting: dict[uuid.UUID, int] = {}
    for c in cands:
        fields = get_posting_fields(session, c.posting_id, user_id=user_id)
        if fields is None:
            continue
        recruit = get_recruit_fields(session, c.posting_id, user_id=user_id)
        # 분야별 색인이 끝난 공고만(청크 수 = 분야 수). 아직 합본 1청크면 분야를 모른다
        if recruit and chunks.get(c.posting_id) == len(recruit):
            field_by_posting[c.posting_id] = c.best_chunk
            fields = narrow_to_field(fields, recruit, c.best_chunk)
        keyword_by_posting[c.posting_id] = keyword_match_rate(extract_required(fields), held)

    # ④ 하이브리드 재정렬 → 상위 top_k
    recs = rerank(cands, keyword_by_posting, top_k=top_k)
    return [replace(r, field_index=field_by_posting.get(r.posting_id)) for r in recs]


def _chunk_counts(session: Session, posting_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """공고별 (현재 모델 버전) 임베딩 청크 수."""
    if not posting_ids:
        return {}
    rows = session.execute(
        select(JobPostingEmbedding.source_id, func.count())
        .where(
            JobPostingEmbedding.source_id.in_(posting_ids),
            JobPostingEmbedding.model_version == MODEL_VERSION,
        )
        .group_by(JobPostingEmbedding.source_id)
    )
    return dict(rows.all())
