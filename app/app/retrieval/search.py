"""C6 — 권한 사전 필터 검색 (retriever).

C2 정책 로더가 만든 WHERE를 벡터 검색에 **강제로** 붙인다. 필터 없는 검색 경로는 두지 않는다(spec 8.2).
- 공개 인덱스(공고): 전원 열람 가능 → 접근 필터 없음.
- 개인 인덱스(자소서·경험): C2 권한 WHERE(소유·공유·등급) + 소프트 삭제 제외(B 요청) 강제.

런타임 동작은 `poc/c3_c6_e2e_poc.py`로 검증됨(실 A1 mask + bge-m3(1024) + pgvector + C2 필터, ALL PASS).
유사도는 코사인(bge-m3 정규화) → `cosine_distance`. 필터+HNSW 조합은 iterative_scan으로 정확도 유지(C1 결론).

가드레일(A8) 연결: spec §8.2 시그니처 `search(query, role, user_id, top_k)`는 `PersonalRetriever`가
A8 `Retriever` 규약 그대로 구현한다(질의문 → 임베딩 → `search_personal` → `Chunk`). docs/C6.md.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.guardrail.pipeline import Chunk
from app.models.embedding import MODEL_VERSION, JobPostingEmbedding, UserProfileEmbedding
from app.models.posting import JobPosting
from app.policy.policy import Policy, build_where, default_matrix_path
from app.retrieval.embedder import Embedder

#: 정책 매트릭스 1회 로드. 경로는 env `POLICY_MATRIX_PATH`(D2 공식본) 우선, 없으면 번들.
_policy = Policy.load(default_matrix_path())

#: 필터와 함께 HNSW를 쓸 때 ANN이 필터를 건너뛰어 누락하는 걸 막는다(C1 결론)
_ITERATIVE_SCAN = "SET LOCAL hnsw.iterative_scan = 'strict_order'"


def search_public(
    session: Session,
    query_embedding: list[float],
    *,
    region_codes: list[str] | None = None,
    job_codes: list[str] | None = None,
    top_k: int = 20,
):
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
    )
    # C8 추천 필터(지역·직무) — 검색 WHERE에 얹어 사전 필터(사후 아님). 값은 사용자 선택(런타임).
    if region_codes:
        stmt = stmt.where(JobPosting.region_code.in_(region_codes))
    if job_codes:
        stmt = stmt.where(JobPosting.job_code.in_(job_codes))
    stmt = stmt.order_by(dist).limit(top_k)
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

    C2가 생성한 권한 WHERE(본인 소유 / 운영자 mask-all 등) + `deleted_at IS NULL`.

    **공유(멘토) 경로는 검색에서 제외한다(B 결정 2026-10-23).** 공유는 자소서의 '공유 시점 버전'만
    보여줘야 하는데 개인 인덱스는 최신본으로 갱신돼 검색이 **공유 이후 수정본**을 돌려준다(버전 고정 불가).
    그래서 `scope=shared` 조건을 WHERE에서 빼고, 멘토의 자소서 열람은 **B10 API(고정 버전)로만** 한다
    (B10이 공유 시점 버전을 고정). 멘토용 AI 검색이 생기면 '공유 시점 버전 청크'를 따로 인덱싱해 재설계.
    """
    if not role or not user_id:
        raise ValueError("role and user_id are required")

    # 공유 경로 제외: shared scope는 버전 고정이 안 돼 검색으로 안 돌려준다(위 docstring). 현재 shared는
    # 멘토뿐 → 멘토는 개인 인덱스에서 0건(자소서는 B10 전용). 다른 scope(own/all)만 WHERE로.
    conds = [c for c in _policy.retrieval_filter(role, user_id) if c.scope != "shared"]
    where_sql, params = build_where(conds, user_id=user_id)  # grade/owner_id (shared 제외)

    session.execute(text(_ITERATIVE_SCAN))

    dist = UserProfileEmbedding.embedding.cosine_distance(query_embedding)
    stmt = (
        select(
            UserProfileEmbedding.id,
            UserProfileEmbedding.source_type,
            UserProfileEmbedding.source_id,
            UserProfileEmbedding.chunk_index,
            UserProfileEmbedding.content,  # B가 저장 때 토큰화한 본문(spec §8.3) — 원문 PII 없음
            UserProfileEmbedding.grade,
            dist.label("distance"),
        )
        # 정책 조건은 OR 묶음이라 괄호로 감싼다. 없으면 뒤의 AND가 마지막 OR 항에만 걸린다(C6 괄호 수정)
        .where(text(f"({where_sql})").bindparams(**params))
        .where(UserProfileEmbedding.deleted_at.is_(None))  # 소프트 삭제 제외(B 요청, 30일 전까지)
        .where(UserProfileEmbedding.model_version == MODEL_VERSION)  # 버전 혼재 방지(적대적 패스)
        .order_by(dist)
        .limit(top_k)
    )
    return session.execute(stmt).all()


# --------------------------------------------------------------------------
# 가드레일(A8) 연결 — spec §8.2 `search(query, role, user_id, top_k)`
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class PolicyChunk(Chunk):
    """A8 `Chunk` + 정책 판정. `Chunk`이므로 파이프라인은 그대로 받는다.

    `decision`은 C2 매트릭스의 role×grade 판정(allow/mask). 검색은 WHERE에서 이미 걸렀으므로
    여기서 거르지 않고 **표시만** 한다(거르는 곳이 둘이면 한쪽이 바뀔 때 구멍). 본문은 이미
    토큰화돼 있어 다시 가리지 않는다 — 빠진 건 mask 판정 신호(spec §8.4·§9.1)라 그것만 싣는다.
    """

    decision: str


def doc_id_of(source_type: str, source_id: object, chunk_index: int) -> str:
    """감사 로그 `doc_ids`용 원문 기준 식별자(예: `resume:<uuid>#0`). 재색인해도 바뀌지 않는다."""
    return f"{source_type}:{source_id}#{chunk_index}"


class PersonalRetriever:
    """A8 `Retriever` 규약 구현: `async search(query, *, role, user_id, top_k) -> list[Chunk]`.

    질의문을 **색인과 같은 임베더**로 벡터화해 `search_personal`(C2 WHERE 강제)을 부른다.
    대상은 개인 인덱스만(공고는 외부 텍스트라 인젝션 표면 — A11은 `get_posting_fields`로 받음).
    세션은 호출마다 직접 연다(`DbAuditSink`와 같은 방식). DB·임베딩은 동기라 스레드에서 돈다.
    임베더 오류는 그대로 올린다 — 빈 결과로 삼키면 "검색 0건"과 구분이 안 된다.
    """

    def __init__(
        self,
        embedder: Embedder,
        *,
        session_factory: Callable[[], AbstractContextManager[Session]] = SessionLocal,
        policy: Policy | None = None,
    ):
        self._embedder = embedder
        self._session_factory = session_factory
        self._policy = policy or _policy  # 검색 WHERE와 같은 정책 객체 → 판정이 어긋나지 않게

    async def search(self, query: str, *, role: str, user_id: str, top_k: int) -> list[Chunk]:
        if not role or not user_id:  # 임베딩 호출 전에 막는다(필터 없는 경로 차단)
            raise ValueError("role and user_id are required")
        return await asyncio.to_thread(self._search, query, role, user_id, top_k)

    def _search(self, query: str, role: str, user_id: str, top_k: int) -> list[Chunk]:
        vec = self._embedder.embed([query])[0]
        with self._session_factory() as db:
            rows = search_personal(db, vec, role=role, user_id=user_id, top_k=top_k)
        return [
            PolicyChunk(
                doc_id=doc_id_of(r.source_type, r.source_id, r.chunk_index),
                grade=r.grade,
                text=r.content,
                decision=self._policy.decision(role, r.grade)[0],
            )
            for r in rows
        ]


def build_retriever(embedder: Embedder | None = None) -> PersonalRetriever | None:
    """가드레일 주입용. 임베더가 없으면 `None` → retriever 미주입(검색 단계 생략, 현행 동작).

    운영 임베더(D bge-m3 서빙)가 생기면 그 클라이언트를 넘기면 켜진다. 평가 환경에만 로컬 임베더를
    붙이지 않는다 — 평가가 운영과 다른 경로를 재게 된다(docs/C6.md 결정 3).
    """
    if embedder is None:
        return None
    return PersonalRetriever(embedder)
