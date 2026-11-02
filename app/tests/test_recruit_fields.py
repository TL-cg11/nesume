"""공고 하나에 모집분야가 여럿일 때 — 분야별 색인·자소서에 맞는 분야·그 분야로만 분석(docs/C4.md)."""
import uuid
from types import SimpleNamespace

from sqlalchemy import select

from app.features.recommend import service as rec_service
from app.features.recommend.rerank import aggregate_candidates
from app.features.skill_gap import router as gaps_router
from app.models.embedding import EMBED_DIM, MODEL_VERSION, JobPostingEmbedding
from app.models.posting import JobPosting
from app.postings.read import narrow_to_field
from app.retrieval.reindex import reindex_postings

_FIELDS = [
    {"name": "일반행정", "job_content": "문서 관리와 회계 지원", "career": "신입", "edu": None,
     "certificates": None},
    {"name": "AI", "job_content": "Kafka 기반 데이터 파이프라인", "career": "경력", "edu": None,
     "certificates": "정보처리기사"},
]


def _vec(i: int) -> list[float]:
    v = [0.0] * EMBED_DIM
    v[i] = 1.0
    return v


class _Embedder:
    def __init__(self):
        self.texts = []

    def embed(self, texts):
        self.texts.extend(texts)
        return [_vec(len(self.texts) % EMBED_DIM) for _ in texts]


def _posting(session, recruit=None, **kw):
    p = JobPosting(
        source="work24_open", link_key=uuid.uuid4().hex, content_hash=uuid.uuid4().hex,
        title=kw.pop("title", "신입 채용"), job_content="일반행정: 문서 관리\nAI: Kafka",
        recruit_fields=recruit, **kw,
    )
    session.add(p)
    session.flush()
    return p


def _chunks(session, pid):
    return session.execute(
        select(JobPostingEmbedding)
        .where(JobPostingEmbedding.source_id == pid)
        .order_by(JobPostingEmbedding.chunk_index)
    ).scalars().all()


# --- 색인 -------------------------------------------------------------------------

def test_multi_field_posting_gets_one_chunk_per_field(db_session):
    p = _posting(db_session, recruit=_FIELDS)
    emb = _Embedder()
    reindex_postings(db_session, emb)
    db_session.flush()
    rows = _chunks(db_session, p.id)
    assert [r.chunk_index for r in rows] == [0, 1]
    assert "회계" in rows[0].content and "Kafka" not in rows[0].content  # 다른 분야 글이 안 섞임
    assert "Kafka" in rows[1].content and "회계" not in rows[1].content
    calls = len(emb.texts)
    again = reindex_postings(db_session, emb)
    assert again["embedded"] == 0 and len(emb.texts) == calls  # 안 바뀌면 다시 안 함


def test_single_field_posting_stays_one_chunk(db_session):
    p = _posting(db_session, recruit=_FIELDS[:1])
    reindex_postings(db_session, _Embedder())
    db_session.flush()
    assert [r.chunk_index for r in _chunks(db_session, p.id)] == [0]


# --- 분야 좁히기 ---------------------------------------------------------------------

def test_narrow_to_field_uses_that_field_only():
    base = {"title": "t", "job_content": "합본", "certificates": "공통 자격"}
    out = narrow_to_field(base, _FIELDS, 1)
    assert out["job_content"] == "AI\nKafka 기반 데이터 파이프라인"
    assert out["certificates"] == "정보처리기사"
    assert narrow_to_field(base, _FIELDS, None) == base
    assert narrow_to_field(base, _FIELDS, 5) == base  # 범위 밖이면 합본 그대로


def test_aggregate_keeps_best_chunk():
    pid = uuid.uuid4()
    cands = aggregate_candidates([(pid, 0.6, 0), (pid, 0.2, 1), (pid, 0.4, 0)])
    assert cands[0].best_chunk == 1 and abs(cands[0].vector_score - 0.8) < 1e-9


# --- 추천: 자소서에 맞는 분야 ------------------------------------------------------------

def _embed_chunks(session, pid, vecs):
    for i, v in enumerate(vecs):
        session.add(JobPostingEmbedding(
            source_id=pid, chunk_index=i, content=f"c{i}", model_version=MODEL_VERSION, embedding=v,
        ))
    session.flush()


def test_recommend_picks_matching_field_and_scores_its_keywords(db_session):
    multi = _posting(db_session, recruit=_FIELDS)
    _embed_chunks(db_session, multi.id, [_vec(0), _vec(1)])
    pending = _posting(db_session, recruit=_FIELDS)  # 분야는 있지만 아직 합본 1청크(색인 전)
    _embed_chunks(db_session, pending.id, [_vec(1)])

    def required(fields):  # 분야로 좁혀졌으면 그 분야 글만 보인다
        return ["kafka"] if "Kafka" in (fields.get("job_content") or "") else ["excel"]

    recs = rec_service.recommend(
        db_session, user_id="u", held_keys=["kafka"], query_vectors=[_vec(1)],
        required_extractor=required, top_k=50,
    )
    by_id = {r.posting_id: r for r in recs}
    assert by_id[multi.id].field_index == 1  # 자소서(질의)와 가까운 AI 분야
    assert by_id[multi.id].keyword_score == 1.0  # AI 분야 요건(kafka)으로만 셈
    assert by_id[pending.id].field_index is None  # 분야별 색인 전이면 분야를 단정하지 않음


# --- 역량 갭: 그 분야 글로만 ---------------------------------------------------------------

def test_learning_gaps_narrows_to_field(monkeypatch):
    seen = {}
    monkeypatch.setattr(gaps_router, "gather_evidence", lambda *a, **k: object())
    posting = {"title": "t", "job_content": "합본"}
    monkeypatch.setattr(gaps_router, "get_posting_fields", lambda *a, **k: posting)
    monkeypatch.setattr(gaps_router, "get_recruit_fields", lambda *a, **k: _FIELDS)

    def prepare(f):
        seen["job_content"] = f.job_content
        return SimpleNamespace(fields=f)

    monkeypatch.setattr(gaps_router, "prepare_posting", prepare)
    monkeypatch.setattr(gaps_router, "extract", lambda f: [])
    report = SimpleNamespace(matches=[], counts=lambda: {})
    monkeypatch.setattr(gaps_router, "compare", lambda kws, ev: report)
    req = gaps_router.LearningGapsRequest(resume_id=uuid.uuid4(), posting_id=uuid.uuid4(), field_index=0)
    gaps_router.learning_gaps_for(req, SimpleNamespace(sub="u"), db=None)
    assert seen["job_content"] == "일반행정\n문서 관리와 회계 지원"
