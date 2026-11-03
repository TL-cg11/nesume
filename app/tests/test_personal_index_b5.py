"""B5 저장 즉시 개인 인덱스 반영(11/2): 표시(mark) → 커밋 뒤 백그라운드 → 배치와 같은 글로 색인."""
import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import CurrentUser, get_current_user
from app.db import SessionLocal
from app.features import personal_index
from app.features.experiences import service as exp_service
from app.features.experiences.reader import tokenized_experience_doc, tokenized_experience_docs
from app.features.resumes import service as resume_service
from app.features.resumes.reader import tokenized_resume_doc, tokenized_resume_docs
from app.main import app
from app.models import Question, Resume, User
from app.models.embedding import UserProfileEmbedding
from app.retrieval.embedder import EmbeddingError

PHONE = "010-1234-5678"


class FakeEmbedder:
    def __init__(self):
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        return [[0.0] * 1024 for _ in texts]


def _user(db):
    u = User(id=f"pi-{uuid.uuid4()}")
    db.add(u)
    db.flush()
    return u.id


def _resume(db, owner, bodies):
    r = Resume(owner_id=owner, title="t")
    db.add(r)
    db.flush()
    qs = []
    for i, b in enumerate(bodies):
        q = Question(resume_id=r.id, owner_id=owner, title=f"q{i}", position=i)
        db.add(q)
        db.flush()
        if b:
            resume_service.create_version(db, owner, r.id, q.id, b, "manual")
        qs.append(q)
    return r, qs


@pytest.fixture(autouse=True)
def _no_experience_hook_side_effect(monkeypatch):
    yield
    app.dependency_overrides.clear()


# --- 글 형식은 배치와 같다 ---------------------------------------------------------

def test_single_doc_matches_batch_format(db_session):
    owner = _user(db_session)
    r, _ = _resume(db_session, owner, [f"첫 문항 {PHONE}", None, "셋째"])
    e = exp_service.create_experience(db_session, owner, {"title": "경험", "type": "프로젝트", "tags": ["a"]})
    batch_r = next(d for d in tokenized_resume_docs(db_session) if d["id"] == r.id)
    batch_e = next(d for d in tokenized_experience_docs(db_session) if d["id"] == e.id)
    assert tokenized_resume_doc(db_session, r.id) == batch_r
    assert tokenized_experience_doc(db_session, e.id) == batch_e
    assert PHONE not in batch_r["text"], "토큰화 상태(원문 복원 안 함)"
    r.deleted_at = datetime.now(UTC)
    db_session.flush()
    assert tokenized_resume_doc(db_session, r.id) is None


# --- 색인 하나 ----------------------------------------------------------------------

def test_index_one_embeds_skips_unchanged_and_clears_empty(db_session):
    owner = _user(db_session)
    r, (q,) = _resume(db_session, owner, ["본문입니다"])
    emb = FakeEmbedder()
    assert personal_index.index_one(db_session, emb, "resume", r.id) == "embedded"
    row = db_session.scalars(select(UserProfileEmbedding).where(UserProfileEmbedding.source_id == r.id)).one()
    assert (row.owner_id, row.source_type, row.content) == (owner, "resume", "본문입니다")
    assert personal_index.index_one(db_session, emb, "resume", r.id) == "unchanged"
    assert emb.calls == 1
    resume_service.create_version(db_session, owner, r.id, q.id, "고친 본문", "manual")
    assert personal_index.index_one(db_session, emb, "resume", r.id) == "embedded" and emb.calls == 2
    q.deleted_at = datetime.now(UTC)  # 문항을 지워 글이 비면 예전 벡터를 지운다
    db_session.flush()
    assert personal_index.index_one(db_session, emb, "resume", r.id) == "empty"
    rows = select(UserProfileEmbedding).where(UserProfileEmbedding.source_id == r.id)
    assert db_session.scalars(rows).all() == []
    assert personal_index.index_one(db_session, emb, "resume", uuid.uuid4()) == "gone"


# --- 저장 → 커밋 뒤 백그라운드 ---------------------------------------------------------

def test_background_run_embeds_outside_db_session(monkeypatch):
    """백그라운드 경로: 읽기·쓰기 세션 사이에서 임베딩(세션을 잡지 않음), 결과는 배치와 같다."""
    emb = FakeEmbedder()
    monkeypatch.setattr("app.retrieval.embedder.HttpEmbedder", lambda *a, **k: emb)
    monkeypatch.setattr(personal_index, "_embedding_url", lambda: "http://embedder:8080")
    with SessionLocal.begin() as db:
        owner = _user(db)
        r, _ = _resume(db, owner, [f"연락 {PHONE}"])
        rid = r.id
    personal_index.run([("resume", rid)])
    personal_index.run([("resume", rid)])
    assert emb.calls == 1, "두 번째는 변경 없음"
    with SessionLocal() as db:
        [row] = db.scalars(select(UserProfileEmbedding).where(UserProfileEmbedding.source_id == rid)).all()
        assert row.owner_id == owner and PHONE not in row.content


@pytest.fixture
def submitted(monkeypatch):
    got = []
    monkeypatch.setattr(personal_index, "submit", lambda items: got.extend(items))
    monkeypatch.setattr(personal_index, "_embedding_url", lambda: "http://embedder:8080")
    return got


def _client(sub):
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(sub=sub)
    return TestClient(app)


def test_saving_version_and_experience_schedules_after_commit(submitted):
    c = _client(f"pi-{uuid.uuid4()}")
    r = c.post("/resumes", json={"title": "색인"}).json()
    q = c.post(f"/resumes/{r['id']}/questions", json={"title": "q"}).json()
    assert submitted == [], "자소서·문항 생성만으로는 글이 없다"
    c.post(f"/resumes/{r['id']}/questions/{q['id']}/versions", json={"body": "본문"})
    assert submitted == [("resume", uuid.UUID(r["id"]))]
    e = c.post("/experiences", json={"title": "경험", "type": "프로젝트"}).json()
    assert submitted[-1] == ("experience", uuid.UUID(e["id"]))


def test_nothing_scheduled_without_embedding_url_or_on_rollback(monkeypatch):
    got = []
    monkeypatch.setattr(personal_index, "submit", lambda items: got.extend(items))
    monkeypatch.setattr(personal_index, "_embedding_url", lambda: None)
    c = _client(f"pi-{uuid.uuid4()}")
    r = c.post("/resumes", json={"title": "색인"}).json()
    q = c.post(f"/resumes/{r['id']}/questions", json={"title": "q"}).json()
    c.post(f"/resumes/{r['id']}/questions/{q['id']}/versions", json={"body": "본문"})
    assert got == [], "EMBEDDING_URL 없으면 아무것도 안 함"
    monkeypatch.setattr(personal_index, "_embedding_url", lambda: "http://embedder:8080")
    db = SessionLocal()
    personal_index.mark(db, "resume", uuid.UUID(r["id"]))
    db.rollback()
    db.close()
    assert got == [], "롤백되면 색인 안 함"


def test_run_survives_embedder_failure(monkeypatch):
    class Down:
        def __init__(self, *a, **k):
            pass

        def embed(self, texts):
            raise EmbeddingError("임베딩 요청 실패: URLError")
    monkeypatch.setattr("app.retrieval.embedder.HttpEmbedder", Down)
    monkeypatch.setattr(personal_index, "_embedding_url", lambda: "http://embedder:8080")
    with SessionLocal.begin() as db:
        owner = _user(db)
        r, _ = _resume(db, owner, ["본문"])
        rid = r.id
    warned = []
    monkeypatch.setattr(personal_index.logger, "warning", lambda msg, **k: warned.append(msg))
    personal_index.run([("resume", rid)])  # 예외가 밖으로 나오지 않는다
    assert warned == ["personal_index_failed"]
