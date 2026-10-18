"""B5 경험 데이터 관리 API."""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import CurrentUser, get_current_user
from app.db import SessionLocal
from app.features.experiences import index_hooks
from app.features.resumes import pii_hooks
from app.main import app
from app.models import Experience


def _as(sub: str) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(sub=sub)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def alice():
    return _as(f"alice-{uuid.uuid4()}")


def _exp(c, **kw):
    body = {"title": "캡스톤 프로젝트", "type": "프로젝트", **kw}
    r = c.post("/experiences", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _question(c):
    rid = c.post("/resumes", json={"title": "자소서"}).json()["id"]
    qid = c.post(f"/resumes/{rid}/questions", json={"title": "지원 동기"}).json()["id"]
    return rid, qid


# --- CRUD -------------------------------------------------------------------

def test_experience_crud_and_soft_delete(alice):
    e = _exp(alice, period_start="2025-03-01", period_end="2025-06-30", role="백엔드",
             tech_stack=["FastAPI", "PostgreSQL"], outcome="응답 시간 40% 단축",
             detail="상세 서술", tags=["백엔드", "성능"])
    assert e["tech_stack"] == ["FastAPI", "PostgreSQL"] and e["tags"] == ["백엔드", "성능"]

    updated = alice.patch(f"/experiences/{e['id']}", json={"outcome": "응답 시간 50% 단축"}).json()
    assert updated["outcome"] == "응답 시간 50% 단축" and updated["role"] == "백엔드"

    assert [x["id"] for x in alice.get("/experiences").json()] == [e["id"]]
    assert alice.delete(f"/experiences/{e['id']}").status_code == 204
    assert alice.get("/experiences").json() == []
    assert alice.get(f"/experiences/{e['id']}").status_code == 404


@pytest.mark.parametrize("field", ["grade", "owner_id", "deleted_at"])
def test_server_controlled_fields_rejected(alice, field):
    assert alice.post("/experiences", json={"title": "t", "type": "x", field: "v"}).status_code == 422


def test_list_item_length_limited(alice):
    r = alice.post("/experiences", json={"title": "t", "type": "x", "tags": ["가" * 51]})
    assert r.status_code == 422


# --- 태그 필터 (OR) ---------------------------------------------------------

def test_tag_filter_matches_any(alice):
    a = _exp(alice, title="A", tags=["백엔드"])
    b = _exp(alice, title="B", tags=["프론트"])
    _exp(alice, title="C", tags=["디자인"])
    got = {x["id"] for x in alice.get("/experiences", params=[("tags", "백엔드"), ("tags", "프론트")]).json()}
    assert got == {a["id"], b["id"]}
    assert len(alice.get("/experiences").json()) == 3
    assert alice.get("/experiences", params={"tags": "없는태그"}).json() == []


# --- PII 처리 지점 ----------------------------------------------------------

@pytest.fixture
def fake_tokenizer(monkeypatch):
    """PII '010-1234-5678'을 토큰으로 바꾸는 가짜 A1·B7."""
    monkeypatch.setattr(pii_hooks, "tokenize_for_storage",
                        lambda owner, t: t.replace("010-1234-5678", "[PHONE_1]"))
    monkeypatch.setattr(pii_hooks, "restore_for_owner",
                        lambda owner, req, t: t.replace("[PHONE_1]", "010-1234-5678"))


def test_all_string_fields_tokenized_on_save_and_restored_for_owner(alice, fake_tokenizer):
    pii = "010-1234-5678"
    e = _exp(alice, title=f"제목 {pii}", type=f"유형{pii}", role=f"역할 {pii}", outcome=f"성과 {pii}",
             detail=f"상세 {pii}", tech_stack=[f"기술 {pii}"], tags=[f"태그 {pii}"])
    with SessionLocal() as db:
        row = db.scalar(select(Experience).where(Experience.id == uuid.UUID(e["id"])))
    stored = [row.title, row.type, row.role, row.outcome, row.detail, *row.tech_stack, *row.tags]
    assert all("[PHONE_1]" in v and pii not in v for v in stored), stored
    assert e["detail"] == f"상세 {pii}" and e["tags"] == [f"태그 {pii}"]


def test_tag_filter_uses_tokenized_value(alice, fake_tokenizer):
    e = _exp(alice, tags=["연락 010-1234-5678"])
    got = alice.get("/experiences", params={"tags": "연락 010-1234-5678"}).json()
    assert [x["id"] for x in got] == [e["id"]]


def test_sensitive_input_blocked_and_not_saved(alice, monkeypatch):
    def block(text):
        if "900101-1234567" in text:
            raise pii_hooks.SensitiveInputBlocked()
    monkeypatch.setattr(pii_hooks, "ensure_no_sensitive", block)

    r = alice.post("/experiences", json={"title": "t", "type": "x", "detail": "주민번호 900101-1234567"})
    assert r.status_code == 422
    assert "민감정보" in r.json()["detail"]
    assert alice.get("/experiences").json() == []

    e = _exp(alice)
    r = alice.patch(f"/experiences/{e['id']}", json={"tags": ["900101-1234567"]})
    assert r.status_code == 422
    assert alice.get(f"/experiences/{e['id']}").json()["tags"] == []


def test_index_hook_called_on_create_and_update_only(alice, monkeypatch):
    calls = []
    monkeypatch.setattr(index_hooks, "index_experience", lambda owner, eid: calls.append(str(eid)))
    e = _exp(alice)
    alice.patch(f"/experiences/{e['id']}", json={"title": "수정"})
    alice.delete(f"/experiences/{e['id']}")
    assert calls == [e["id"], e["id"]]


# --- 자소서 문항에 끌어오기 -------------------------------------------------

def test_link_unlink_and_list(alice):
    rid, qid = _question(alice)
    e1, e2 = _exp(alice, title="E1"), _exp(alice, title="E2")
    base = f"/resumes/{rid}/questions/{qid}/experiences"

    assert alice.post(base, json={"experience_id": e1["id"]}).status_code == 201
    assert alice.post(base, json={"experience_id": e1["id"]}).status_code == 200  # 중복 연결은 그대로
    alice.post(base, json={"experience_id": e2["id"]})
    assert [x["title"] for x in alice.get(base).json()] == ["E1", "E2"]

    assert alice.delete(f"{base}/{e1['id']}").status_code == 204
    assert alice.delete(f"{base}/{e1['id']}").status_code == 404
    assert [x["title"] for x in alice.get(base).json()] == ["E2"]


def test_soft_deleted_experience_hidden_from_links(alice):
    rid, qid = _question(alice)
    e = _exp(alice)
    base = f"/resumes/{rid}/questions/{qid}/experiences"
    alice.post(base, json={"experience_id": e["id"]})
    alice.delete(f"/experiences/{e['id']}")
    assert alice.get(base).json() == []
    assert alice.post(base, json={"experience_id": e["id"]}).status_code == 404


def test_links_unavailable_after_question_deleted(alice):
    rid, qid = _question(alice)
    e = _exp(alice)
    base = f"/resumes/{rid}/questions/{qid}/experiences"
    alice.post(base, json={"experience_id": e["id"]})
    alice.delete(f"/resumes/{rid}/questions/{qid}")
    assert alice.get(base).status_code == 404


# --- 소유자 격리 (IDOR) -----------------------------------------------------

def test_other_user_isolation():
    a_sub, b_sub = f"alice-{uuid.uuid4()}", f"bob-{uuid.uuid4()}"
    alice = _as(a_sub)
    a_exp = _exp(alice, tags=["공통태그"])
    a_rid, a_qid = _question(alice)

    bob = _as(b_sub)
    b_exp = _exp(bob, tags=["공통태그"])
    b_rid, b_qid = _question(bob)

    assert bob.get(f"/experiences/{a_exp['id']}").status_code == 404
    assert bob.patch(f"/experiences/{a_exp['id']}", json={"title": "x"}).status_code == 404
    assert bob.delete(f"/experiences/{a_exp['id']}").status_code == 404
    assert [x["id"] for x in bob.get("/experiences", params={"tags": "공통태그"}).json()] == [b_exp["id"]]
    # 타인 경험을 내 문항에, 내 경험을 타인 문항에 연결 불가
    assert bob.post(f"/resumes/{b_rid}/questions/{b_qid}/experiences",
                    json={"experience_id": a_exp["id"]}).status_code == 404
    assert bob.post(f"/resumes/{a_rid}/questions/{a_qid}/experiences",
                    json={"experience_id": b_exp["id"]}).status_code == 404
    assert bob.get(f"/resumes/{a_rid}/questions/{a_qid}/experiences").status_code == 404

    alice = _as(a_sub)
    assert alice.get(f"/experiences/{a_exp['id']}").json()["title"] == "캡스톤 프로젝트"
