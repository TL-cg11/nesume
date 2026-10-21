"""C6 — 권한 사전 필터 검색 (retriever).

C2 정책 로더가 만든 WHERE를 벡터 검색에 **강제로** 붙인다. 필터 없는 검색 경로는 두지 않는다(spec 8.2).
- 공개 인덱스(공고): 전원 열람 가능 → 접근 필터 없음.
- 개인 인덱스(자소서·경험): C2 권한 WHERE(소유·공유·등급) + 소프트 삭제 제외(B 요청) 강제.

런타임 동작은 `poc/c3_c6_e2e_poc.py`로 검증됨(실 A1 mask + bge-m3(1024) + pgvector + C2 필터, ALL PASS).
유사도는 코사인(bge-m3 정규화) → `cosine_distance`. 필터+HNSW 조합은 iterative_scan으로 정확도 유지(C1 결론).
"""
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import Session

import app.policy.policy as policy_mod
from app.models.embedding import MODEL_VERSION, JobPostingEmbedding, UserProfileEmbedding
from app.models.posting import JobPosting
from app.policy.policy import build_where

#: 정책은 `app/app/policy/matrix.yaml`(D2 공식본 나오면 교체)에서 1회 로드
_policy = policy_mod.Policy.load(str(Path(policy_mod.__file__).parent / "matrix.yaml"))

#: 필터와 함께 HNSW를 쓸 때 ANN이 필터를 건너뛰어 누락하는 걸 막는다(C1 결론)
_ITERATIVE_SCAN = "SET LOCAL hnsw.iterative_scan = 'strict_order'"


def search_public(session: Session, query_embedding: list[float], *, top_k: int = 20):
    """공개 인덱스(공고) 검색. grade=public뿐이라 역할 접근 필터는 없다.

    단 적대적 패스 결과로 두 가지를 강제한다(docs/C6.md):
    - **비활성·검토대기 공고 제외** — `job_postings` 조인으로 `is_active`·`not needs_review`.
      (마감·백스톱 처리분, 식별 불확실 공고가 추천에 뜨지 않게.)
    - **임베딩 버전 일치** — 모델 버전 혼재 시 검색 품질 붕괴 방지.
    """
    dist = JobPostingEmbedding.embedding.cosine_distance(query_embedding)
    stmt = (
        select(JobPostingEmbedding.id, JobPostingEmbedding.source_id, dist.label("distance"))
        .join(JobPosting, JobPosting.id == JobPostingEmbedding.source_id)
        .where(JobPosting.is_active.is_(True), JobPosting.needs_review.is_(False))
        .where(JobPostingEmbedding.model_version == MODEL_VERSION)
        .order_by(dist)
        .limit(top_k)
    )
    return session.execute(stmt).all()


def search_personal(
    session: Session,
    query_embedding: list[float],
    *,
    role: str,
    user_id: str,
    top_k: int = 20,
):
    """개인 인덱스(자소서·경험) 검색. role·user_id 필수(필터 없는 경로 차단).

    C2가 생성한 권한 WHERE(본인 소유 / 멘토 유효 공유 / 운영자 mask-all 등) + `deleted_at IS NULL`.
    """
    if not role or not user_id:
        raise ValueError("role and user_id are required")

    conds = _policy.retrieval_filter(role, user_id)
    where_sql, params = build_where(conds, user_id=user_id)  # grade/owner_id/shared_with(JSONB)

    session.execute(text(_ITERATIVE_SCAN))

    dist = UserProfileEmbedding.embedding.cosine_distance(query_embedding)
    stmt = (
        select(
            UserProfileEmbedding.id,
            UserProfileEmbedding.source_type,
            UserProfileEmbedding.source_id,
            dist.label("distance"),
        )
        .where(text(where_sql).bindparams(**params))
        .where(UserProfileEmbedding.deleted_at.is_(None))  # 소프트 삭제 제외(B 요청, 30일 전까지)
        .where(UserProfileEmbedding.model_version == MODEL_VERSION)  # 버전 혼재 방지(적대적 패스)
        .order_by(dist)
        .limit(top_k)
    )
    # TODO(B 통합): 고등급(sensitive·confidential) 심층 방어 — 벡터 행의 복제된 shared_with만
    #   믿지 말고 원본 `resumes`(shared_with·deleted_at)와 EXISTS 조인으로 재확인(docs/C3.md #1 ③).
    #   B의 resumes 모델(컬럼·관계) 확정 후 추가. 추측 SQL은 접근통제 사고 위험이라 지금은 미구현.
    return session.execute(stmt).all()
