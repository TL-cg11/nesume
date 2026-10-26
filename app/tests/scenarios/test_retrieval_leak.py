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

import uuid
from datetime import UTC, datetime, timedelta

import pytest

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
from app.retrieval.search import search_personal, search_public

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
