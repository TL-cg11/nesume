"""C11 ② 통합 계층 — 실 pgvector에서 개인 인덱스 누출 0 (DB·pgvector 필요 → CI/통합).

① 순수(test_policy_where)가 "정책이 맞는 WHERE를 만드는가"면, 여기선 "그 WHERE가 실제 검색에서
금지 문서를 정말 빼는가"를 본다. 금지 문서를 **쿼리와 동일한 벡터**(가장 가까움)로 심어, 필터가
없다면 반드시 top_k에 들어올 상황에서 **0건**이어야 통과하게 만든다(C6 PoC 방식).

**멘토 공유 경로**(B 결정 2026-10-23): 공유는 '공유 시점 버전'만 보여줘야 하나 개인 인덱스는 최신본으로
갱신된다 → 검색이 공유 이후 수정본을 돌려줄 위험. 그래서 C6가 shared scope를 검색에서 **제외**(자소서
열람은 B10 고정버전 전용). 아래 S-SHARE는 "유효 공유여도 검색엔 0건"을 검증한다.

실행: 테스트 DB + Alembic head(C 임베딩·B users/shares/resumes 포함) + pgvector. conftest `db_session` 사용.
owner_id·shared_with는 `users.id` FK라 시드에서 User 행을 먼저 만든다.
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

import pytest

from app.guardrail.pipeline import Chunk
from app.models.embedding import (
    EMBED_DIM,
    MODEL_VERSION,
    JobPostingEmbedding,
    UserProfileEmbedding,
)
from app.models.posting import JobPosting
from app.models.resume import Resume
from app.models.share import Share
from app.models.user import User
from app.retrieval.search import (
    PersonalRetriever,
    build_retriever,
    search_personal,
    search_public,
)

# 모든 문서·쿼리를 같은 벡터로 → 유사도는 동일, 필터만이 결과를 가른다(가장 가까운데도 빠지는가).
QUERY = [1.0] + [0.0] * (EMBED_DIM - 1)


def _user(session) -> str:
    """User 행 생성 후 id 반환. owner_id·shared_with가 users.id FK라 먼저 있어야 한다."""
    uid = str(uuid.uuid4())
    session.add(User(id=uid))
    session.flush()
    return uid


def _resume(session, owner: str, *, deleted: bool = False) -> Resume:
    r = Resume(owner_id=owner, title="이력서")
    if deleted:
        r.deleted_at = datetime.now(UTC)
    session.add(r)
    session.flush()
    return r


def _emb(session, owner: str, resume_id: uuid.UUID, *, shared_with=None, deleted=False):
    e = UserProfileEmbedding(
        owner_id=owner,
        source_type="resume",
        source_id=resume_id,
        content="[[PHONE_1]] 자기소개",
        model_version=MODEL_VERSION,
        embedding=QUERY,
        shared_with=shared_with or [],
        deleted_at=datetime.now(UTC) if deleted else None,
    )
    session.add(e)
    session.flush()
    return e


def _share(session, resume_id, owner: str, mentor: str) -> Share:
    """유효 공유 1건(만료 전·미취소). CHECK expires_at>created_at 충족."""
    s = Share(
        resume_id=resume_id,
        owner_id=owner,
        shared_with=mentor,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    session.add(s)
    session.flush()
    return s


def _posting(session, *, active: bool = True, review: bool = False) -> JobPosting:
    p = JobPosting(
        source="seoul",
        link_key=str(uuid.uuid4()),
        content_hash=str(uuid.uuid4()),
        is_active=active,
        needs_review=review,
    )
    session.add(p)
    session.flush()
    return p


def _posting_emb(session, posting_id: uuid.UUID) -> JobPostingEmbedding:
    e = JobPostingEmbedding(
        source_id=posting_id, content="공고 본문", model_version=MODEL_VERSION, embedding=QUERY
    )
    session.add(e)
    session.flush()
    return e


def _ids(rows) -> set:
    return {r.source_id for r in rows}


# --------------------------------------------------------------------------
# S-OWN — 소유 경계
# --------------------------------------------------------------------------

def test_own_sees_self_not_others(db_session):
    """S-OWN-1·2: user는 본인 자소서만. 타인 것은 가장 가까운 벡터여도 0건."""
    a, b = _user(db_session), _user(db_session)
    ra, rb = _resume(db_session, a), _resume(db_session, b)
    _emb(db_session, a, ra.id)
    _emb(db_session, b, rb.id)

    got = _ids(search_personal(db_session, QUERY, role="user", user_id=a))
    assert ra.id in got
    assert rb.id not in got  # 타인 문서 누출 0


def test_soft_deleted_excluded(db_session):
    """S-DEL-1: 소프트 삭제된 임베딩은 본인 것이어도 빠진다."""
    a = _user(db_session)
    r = _resume(db_session, a)
    _emb(db_session, a, r.id, deleted=True)
    assert r.id not in _ids(search_personal(db_session, QUERY, role="user", user_id=a))


# --------------------------------------------------------------------------
# S-SHARE — 멘토 공유 경로는 검색에서 제외 (B 결정: 자소서는 B10 고정버전 전용)
# --------------------------------------------------------------------------

def test_mentor_shared_resume_excluded_from_search(db_session):
    """S-SHARE(개정): **유효 공유 + 복제본 멀쩡 + 최신(수정)본**이어도 멘토 검색엔 0건.

    공유 경로를 검색에서 아예 빼므로(scope=shared 제외), '공유 이후 수정본'이 AI로 새지 않는다.
    멘토의 자소서 열람은 B10(고정 버전)으로만.
    """
    owner, mentor = _user(db_session), _user(db_session)
    r = _resume(db_session, owner)
    future = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    _emb(db_session, owner, r.id, shared_with=[{"user_id": mentor, "expires_at": future}])
    _share(db_session, r.id, owner, mentor)  # 유효 공유여도
    assert r.id not in _ids(search_personal(db_session, QUERY, role="mentor", user_id=mentor))


def test_mentor_gets_no_personal_in_search(db_session):
    """멘토는 개인 인덱스에서 아무것도 못 가져온다(공유든 아니든 검색 경로엔 자소서 없음)."""
    owner, mentor = _user(db_session), _user(db_session)
    r = _resume(db_session, owner)
    _emb(db_session, owner, r.id)  # 공유 안 함
    assert search_personal(db_session, QUERY, role="mentor", user_id=mentor) == []


# --------------------------------------------------------------------------
# S-IDX — 인덱스 분리: 공개 검색은 공고만(개인 안 섞임)·비활성/검토대기 제외
# --------------------------------------------------------------------------

def test_public_excludes_personal_index(db_session):
    """S-IDX-1: 개인 임베딩과 공고 임베딩을 같은 벡터로 심어도 `search_public`엔 공고만."""
    a = _user(db_session)
    r = _resume(db_session, a)
    _emb(db_session, a, r.id)        # 개인 인덱스
    p = _posting(db_session)
    _posting_emb(db_session, p.id)   # 공개 인덱스
    got = _ids(search_public(db_session, QUERY))
    assert p.id in got
    assert r.id not in got  # 개인 문서는 공개 검색에 절대 안 뜸


def test_public_excludes_inactive_and_review(db_session):
    """S-IDX-2: 비활성·검토대기 공고는 추천 풀에서 빠진다(활성 정상만)."""
    active = _posting(db_session)
    _posting_emb(db_session, active.id)
    inactive = _posting(db_session, active=False)
    _posting_emb(db_session, inactive.id)
    review = _posting(db_session, review=True)
    _posting_emb(db_session, review.id)

    got = _ids(search_public(db_session, QUERY))
    assert active.id in got
    assert inactive.id not in got
    assert review.id not in got


# --------------------------------------------------------------------------
# S-NOFILTER — 필터 없는 경로 차단(런타임에서도)
# --------------------------------------------------------------------------

@pytest.mark.parametrize(("role", "uid"), [("", "u"), ("user", "")])
def test_search_personal_requires_role_and_user(db_session, role, uid):
    """S-NOFILTER-1: role·user_id 없이는 검색 자체가 거부된다(DB 접근 전)."""
    with pytest.raises(ValueError):
        search_personal(db_session, QUERY, role=role, user_id=uid)


# --------------------------------------------------------------------------
# A8 연결 — spec §8.2 `search(query, role, user_id, top_k)` (PersonalRetriever)
# --------------------------------------------------------------------------

class _FakeEmbedder:
    """질의 1건을 QUERY 벡터로. 호출 기록으로 '임베딩 1회'·'필터 없는 호출은 임베딩 전 차단'을 본다."""

    def __init__(self):
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [QUERY for _ in texts]


def _retriever(db_session, embedder=None) -> PersonalRetriever:
    # 테스트 트랜잭션(db_session) 안의 시드를 보도록 같은 세션을 넘긴다(닫지 않게 nullcontext)
    return PersonalRetriever(embedder or _FakeEmbedder(), session_factory=lambda: nullcontext(db_session))


def _search(retriever, *, role, user_id, top_k=5):
    return asyncio.run(retriever.search("자기소개 질의", role=role, user_id=user_id, top_k=top_k))


def test_retriever_returns_chunks_with_text_grade_doc_id(db_session):
    """A8 규약 모양: Chunk(doc_id=원문 기준, grade, text=토큰화 본문). 질의 임베딩은 1회."""
    a = _user(db_session)
    r = _resume(db_session, a)
    _emb(db_session, a, r.id)
    emb = _FakeEmbedder()

    got = _search(_retriever(db_session, emb), role="user", user_id=a)

    assert len(got) == 1
    c = got[0]
    assert isinstance(c, Chunk)
    assert c.doc_id == f"resume:{r.id}#0"
    assert c.grade == "personal"
    assert c.text == "[[PHONE_1]] 자기소개"  # 저장된 토큰화 본문 그대로(원문 PII 없음)
    assert emb.calls == [["자기소개 질의"]]


def test_retriever_marks_decision_by_role(db_session):
    """판정 표시: 본인(user×personal)=allow, 운영자(operator×personal)=mask. 거르지는 않는다."""
    a, op = _user(db_session), _user(db_session)
    r = _resume(db_session, a)
    _emb(db_session, a, r.id)

    own = _search(_retriever(db_session), role="user", user_id=a)
    target = f"resume:{r.id}#0"
    ops = [c for c in _search(_retriever(db_session), role="operator", user_id=op) if c.doc_id == target]

    assert [c.decision for c in own] == ["allow"]
    assert [c.decision for c in ops] == ["mask"]


def test_retriever_keeps_filters(db_session):
    """WHERE는 그대로: 타인 문서·소프트 삭제 0건, 멘토는 개인 인덱스 0건."""
    a, b, mentor = _user(db_session), _user(db_session), _user(db_session)
    ra, rb, rd = _resume(db_session, a), _resume(db_session, b), _resume(db_session, a)
    _emb(db_session, a, ra.id)
    _emb(db_session, b, rb.id)
    _emb(db_session, a, rd.id, deleted=True)

    ids = {c.doc_id for c in _search(_retriever(db_session), role="user", user_id=a)}
    assert ids == {f"resume:{ra.id}#0"}
    assert _search(_retriever(db_session), role="mentor", user_id=mentor) == []


@pytest.mark.parametrize(("role", "uid"), [("", "u"), ("user", "")])
def test_retriever_requires_role_and_user_before_embedding(db_session, role, uid):
    """S-NOFILTER-2: role·user_id 없으면 임베딩·DB 전에 거부."""
    emb = _FakeEmbedder()
    with pytest.raises(ValueError):
        _search(_retriever(db_session, emb), role=role, user_id=uid)
    assert emb.calls == []


def test_build_retriever_without_embedder_is_none():
    """임베더 미설정 → None(가드레일 검색 단계 생략, 현행 동작 유지)."""
    assert build_retriever() is None
    assert isinstance(build_retriever(_FakeEmbedder()), PersonalRetriever)
