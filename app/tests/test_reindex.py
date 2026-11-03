"""C3 실제 임베딩 색인 배치 테스트 (DB 필요, conftest `db_session`). docs/C3.md HttpEmbedder 4~5."""
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.features.experiences import service as exp_service
from app.features.resumes import service as resume_service
from app.models.embedding import EMBED_DIM, JobPostingEmbedding, UserProfileEmbedding
from app.models.posting import JobPosting
from app.retrieval.reindex import posting_priority, reindex_personal, reindex_postings

_PHONE = "010-1234-5678"


class _CountingEmbedder:
    def __init__(self):
        self.texts = []

    def embed(self, texts):
        self.texts.extend(texts)
        return [[0.01] * EMBED_DIM for _ in texts]


def _posting(session, **kw):
    p = JobPosting(
        source=kw.pop("source", "work24_open"), link_key=uuid.uuid4().hex, content_hash=uuid.uuid4().hex,
        title=kw.pop("title", "백엔드 개발자"), job_content=kw.pop("job_content", "Python SQL"), **kw,
    )
    session.add(p)
    session.flush()
    return p


def _rows(session, model, source_id):
    return session.execute(select(model).where(model.source_id == source_id)).scalars().all()


def test_postings_embedded_once_then_unchanged(db_session):
    p = _posting(db_session)
    emb = _CountingEmbedder()
    first = reindex_postings(db_session, emb)
    db_session.flush()
    assert first["embedded"] >= 1 and len(_rows(db_session, JobPostingEmbedding, p.id)) == 1
    calls = len(emb.texts)
    again = reindex_postings(db_session, emb)
    assert again["embedded"] == 0 and len(emb.texts) == calls  # 안 바뀌면 임베딩 호출 0


def test_posting_change_and_demo_rows_replaced(db_session):
    p = _posting(db_session)
    db_session.add(JobPostingEmbedding(source_id=p.id, content="[DEMO] 가짜", embedding=[0.0] * EMBED_DIM))
    db_session.flush()
    reindex_postings(db_session, _CountingEmbedder())
    db_session.flush()
    rows = _rows(db_session, JobPostingEmbedding, p.id)
    assert len(rows) == 1 and not rows[0].content.startswith("[DEMO]")  # 데모 행 교체

    p.job_content = "Kubernetes 운영"
    db_session.flush()
    out = reindex_postings(db_session, _CountingEmbedder())
    db_session.flush()
    rows = _rows(db_session, JobPostingEmbedding, p.id)
    assert out["embedded"] >= 1 and len(rows) == 1 and "Kubernetes" in rows[0].content


def test_posting_text_is_masked(db_session):
    p = _posting(db_session, job_content=f"문의 {_PHONE} 담당자")
    emb = _CountingEmbedder()
    reindex_postings(db_session, emb)
    db_session.flush()
    assert all(_PHONE not in t for t in emb.texts)
    assert _PHONE not in _rows(db_session, JobPostingEmbedding, p.id)[0].content


def test_cap_limits_embeddings(db_session):
    for _ in range(3):
        _posting(db_session)
    out = reindex_postings(db_session, _CountingEmbedder(), cap=1)
    assert out["embedded"] == 1 and out["pending"] >= 2


def test_linked_postings_are_embedded_first(db_session):
    """서울시(링크 없음)가 먼저 들어가 있어도 상한 안에서 공채속보(링크 있음)가 먼저 (docs/C8.md 11-02)."""
    for _ in range(3):
        _posting(db_session, source="seoul")
    linked = _posting(db_session, source_url="https://example.com/job/1")
    out = reindex_postings(db_session, _CountingEmbedder(), cap=1)
    db_session.flush()
    assert out["embedded"] == 1 and len(_rows(db_session, JobPostingEmbedding, linked.id)) == 1


def test_priority_new_before_changed_then_newest_first():
    now = datetime(2026, 11, 2, tzinfo=UTC)
    old = JobPosting(source="seoul", first_seen_at=now - timedelta(days=3))
    new = JobPosting(source="seoul", first_seen_at=now)
    linked = JobPosting(
        source="work24_open", source_url="https://example.com/1", first_seen_at=now - timedelta(days=9)
    )
    order = sorted(
        [(old, False), (new, True), (new, False), (linked, True)],
        key=lambda t: posting_priority(t[0], has_vector=t[1]),
    )
    # 링크 있는 공고(벡터 있어도) → 벡터 없는 새 공고 → 벡터 없는 옛 공고 → 벡터 있는(바뀐) 공고
    assert order == [(linked, True), (new, False), (old, False), (new, True)]


def _resume_with_body(session, owner, body):
    r = resume_service.create_resume(session, owner, title="자소서")
    q = resume_service.create_question(session, r, "지원동기", None, None)
    resume_service.create_version(session, owner, r.id, q.id, body, "manual")
    session.flush()
    return r


def test_personal_uses_tokenized_values_and_copies_meta(db_session):
    owner = f"u-{uuid.uuid4()}"
    r = _resume_with_body(db_session, owner, f"연락처 {_PHONE} 로 주세요. Python 경험")
    r.shared_with = [{"user_id": "mentor-1", "expires_at": "2099-01-01T00:00:00Z"}]
    fields = {"title": "프로젝트", "type": "project", "detail": "SQL 튜닝"}
    e = exp_service.create_experience(db_session, owner, fields)
    db_session.flush()

    emb = _CountingEmbedder()
    out = reindex_personal(db_session, emb)
    db_session.flush()
    assert out["embedded"] >= 2
    assert all(_PHONE not in t for t in emb.texts)  # 원문 복원 안 함 — 토큰화 값만 임베딩

    (row,) = _rows(db_session, UserProfileEmbedding, r.id)
    assert row.owner_id == owner and row.source_type == "resume" and row.grade == r.grade
    assert row.shared_with == r.shared_with and _PHONE not in row.content and "Python" in row.content
    (erow,) = _rows(db_session, UserProfileEmbedding, e.id)
    assert erow.source_type == "experience" and "SQL" in erow.content


def test_personal_skips_deleted_and_unchanged(db_session):
    from datetime import UTC, datetime

    owner = f"u-{uuid.uuid4()}"
    r = _resume_with_body(db_session, owner, "Docker 경험")
    reindex_personal(db_session, _CountingEmbedder())
    db_session.flush()
    emb = _CountingEmbedder()
    reindex_personal(db_session, emb)
    assert not any("Docker" in t for t in emb.texts)  # 안 바뀌면 다시 안 함

    gone = _resume_with_body(db_session, owner, "삭제될 자소서")
    gone.deleted_at = datetime.now(UTC)
    db_session.flush()
    reindex_personal(db_session, _CountingEmbedder())
    db_session.flush()
    assert _rows(db_session, UserProfileEmbedding, gone.id) == []
    assert len(_rows(db_session, UserProfileEmbedding, r.id)) == 1
