"""C11 ② 통합 계층 — 실 pgvector에서 개인 인덱스 누출 0 (DB·pgvector 필요 → CI/통합).

① 순수(test_policy_where)가 "정책이 맞는 WHERE를 만드는가"면, 여기선 "그 WHERE + C6 심층방어가
실제 검색에서 금지 문서를 정말 빼는가"를 본다. 금지 문서를 **쿼리와 동일한 벡터**(가장 가까움)로
심어, 필터가 없다면 반드시 top_k에 들어올 상황에서 **0건**이어야 통과하게 만든다(C6 PoC 방식).

핵심은 **공유 심층방어**(search.py `_SHARES_RECHECK`): 벡터 행의 복제 shared_with가 남아 있어도
원본 `shares`가 끊겼으면(취소·부재) 빠져야 한다. B `shares`/`resumes` 모델 위에서 검증.

실행: 테스트 DB + Alembic head(마이그레이션에 C 임베딩·B shares/resumes 포함) + pgvector 필요.
로컬 순수 실행(`--noconftest`) 대상 아님 — conftest의 `db_session`을 쓴다.
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
from app.retrieval.search import search_personal, search_public

# 모든 문서·쿼리를 같은 벡터로 → 유사도는 동일, 필터만이 결과를 가른다(가장 가까운데도 빠지는가).
QUERY = [1.0] + [0.0] * (EMBED_DIM - 1)


def _uid() -> str:
    return str(uuid.uuid4())


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


def _share(session, resume_id, owner, mentor, *, expired=False, revoked=False) -> Share:
    now = datetime.now(UTC)
    # CHECK expires_at > created_at 때문에 만료본은 created_at을 과거로 당겨 표현한다.
    created = now - timedelta(days=2)
    expires = (now - timedelta(days=1)) if expired else (now + timedelta(days=7))
    s = Share(
        resume_id=resume_id,
        owner_id=owner,
        shared_with=mentor,
        expires_at=expires,
        revoked_at=now if revoked else None,
        created_at=created,
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
    a, b = _uid(), _uid()
    ra, rb = _resume(db_session, a), _resume(db_session, b)
    _emb(db_session, a, ra.id)
    _emb(db_session, b, rb.id)

    got = _ids(search_personal(db_session, QUERY, role="user", user_id=a))
    assert ra.id in got
    assert rb.id not in got  # 타인 문서 누출 0


def test_soft_deleted_excluded(db_session):
    """S-DEL-1: 소프트 삭제된 임베딩은 본인 것이어도 빠진다."""
    a = _uid()
    r = _resume(db_session, a)
    _emb(db_session, a, r.id, deleted=True)
    assert r.id not in _ids(search_personal(db_session, QUERY, role="user", user_id=a))


# --------------------------------------------------------------------------
# S-SHARE / S-DEEP — 공유 경계 + 심층방어
# --------------------------------------------------------------------------

def test_mentor_valid_share_sees(db_session):
    """S-SHARE-1: 유효 공유(복제본 + 원본 shares 둘 다 유효)면 멘토가 본다."""
    owner, mentor = _uid(), _uid()
    r = _resume(db_session, owner)
    future = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    _emb(db_session, owner, r.id, shared_with=[{"user_id": mentor, "expires_at": future}])
    _share(db_session, r.id, owner, mentor)
    assert r.id in _ids(search_personal(db_session, QUERY, role="mentor", user_id=mentor))


def test_mentor_revoked_share_blocked_by_deep_defense(db_session):
    """S-DEEP-1: 벡터 행 복제 shared_with는 남아 있으나 원본 shares가 **취소**면 빠진다(심층방어 핵심)."""
    owner, mentor = _uid(), _uid()
    r = _resume(db_session, owner)
    future = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    # 복제본은 유효한 척(동기화 지연·실패 가정) — C2 WHERE만 보면 통과할 상황
    _emb(db_session, owner, r.id, shared_with=[{"user_id": mentor, "expires_at": future}])
    _share(db_session, r.id, owner, mentor, revoked=True)  # 원본은 취소됨
    assert r.id not in _ids(search_personal(db_session, QUERY, role="mentor", user_id=mentor))


def test_mentor_no_share_row_blocked(db_session):
    """S-DEEP-1 변형: 복제본만 있고 원본 shares가 아예 없으면 빠진다."""
    owner, mentor = _uid(), _uid()
    r = _resume(db_session, owner)
    future = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    _emb(db_session, owner, r.id, shared_with=[{"user_id": mentor, "expires_at": future}])
    # shares 행 없음
    assert r.id not in _ids(search_personal(db_session, QUERY, role="mentor", user_id=mentor))


def test_mentor_resume_deleted_blocked(db_session):
    """S-DEEP-1 변형: 공유는 유효해도 원본 자소서가 삭제(resumes.deleted_at)면 빠진다."""
    owner, mentor = _uid(), _uid()
    r = _resume(db_session, owner, deleted=True)
    future = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    _emb(db_session, owner, r.id, shared_with=[{"user_id": mentor, "expires_at": future}])
    _share(db_session, r.id, owner, mentor)
    assert r.id not in _ids(search_personal(db_session, QUERY, role="mentor", user_id=mentor))


def test_mentor_not_shared_blocked(db_session):
    """S-SHARE-4: 공유된 적 없는 자소서는 멘토가 못 본다(복제본도 shares도 없음)."""
    owner, mentor = _uid(), _uid()
    r = _resume(db_session, owner)
    _emb(db_session, owner, r.id)  # shared_with 비어있음
    assert r.id not in _ids(search_personal(db_session, QUERY, role="mentor", user_id=mentor))


# --------------------------------------------------------------------------
# S-IDX — 인덱스 분리: 공개 검색은 공고만(개인 안 섞임)·비활성/검토대기 제외
# --------------------------------------------------------------------------

def test_public_excludes_personal_index(db_session):
    """S-IDX-1: 개인 임베딩과 공고 임베딩을 같은 벡터로 심어도 `search_public`엔 공고만."""
    a = _uid()
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
    """S-NOFILTER-1: role·user_id 없이는 검색 자체가 거부된다."""
    with pytest.raises(ValueError):
        search_personal(db_session, QUERY, role=role, user_id=uid)
