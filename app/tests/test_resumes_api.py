"""B4 자소서 CRUD + 버전 관리 API."""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import CurrentUser, get_current_user
from app.db import SessionLocal
from app.features.resumes import pii_hooks, service
from app.main import app
from app.models import Version


def _client_for(sub: str) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(sub=sub)
    return TestClient(app)


@pytest.fixture
def alice():
    yield _client_for(f"alice-{uuid.uuid4()}")
    app.dependency_overrides.clear()


@pytest.fixture
def two_users():
    a_sub, b_sub = f"alice-{uuid.uuid4()}", f"bob-{uuid.uuid4()}"

    class Switch:
        def as_(self, sub):
            return _client_for(sub)

    yield Switch(), a_sub, b_sub
    app.dependency_overrides.clear()


def _resume(c, title="네이버 백엔드"):
    r = c.post("/resumes", json={"title": title})
    assert r.status_code == 201, r.text
    return r.json()


def _question(c, rid, title="지원 동기", char_limit=800):
    r = c.post(f"/resumes/{rid}/questions", json={"title": title, "char_limit": char_limit})
    assert r.status_code == 201, r.text
    return r.json()


def _version(c, rid, qid, body):
    r = c.post(f"/resumes/{rid}/questions/{qid}/versions", json={"body": body})
    assert r.status_code == 201, r.text
    return r.json()


# --- 자소서 -----------------------------------------------------------------

def test_resume_crud_and_soft_delete(alice):
    r = _resume(alice)
    assert r["status"] is None

    assert alice.patch(f"/resumes/{r['id']}", json={"status": "작성중"}).json()["status"] == "작성중"
    assert [x["id"] for x in alice.get("/resumes").json()] == [r["id"]]

    assert alice.delete(f"/resumes/{r['id']}").status_code == 204
    assert alice.get("/resumes").json() == []
    assert alice.get(f"/resumes/{r['id']}").status_code == 404


@pytest.mark.parametrize("field", ["grade", "owner_id", "shared_with", "deleted_at"])
def test_server_controlled_fields_rejected(alice, field):
    # 등급·소유자·공유·삭제 상태는 요청으로 지정할 수 없다(B8)
    r = alice.post("/resumes", json={"title": "t", field: "x"})
    assert r.status_code == 422


def test_requires_authentication():
    app.dependency_overrides.clear()
    assert TestClient(app).get("/resumes").status_code == 401


# --- 문항 -------------------------------------------------------------------

def test_question_crud_and_detail(alice):
    r = _resume(alice)
    q1 = _question(alice, r["id"], "지원 동기")
    q2 = _question(alice, r["id"], "성장 과정")
    assert (q1["position"], q2["position"]) == (0, 1)

    alice.patch(f"/resumes/{r['id']}/questions/{q1['id']}", json={"char_limit": 1000})
    detail = alice.get(f"/resumes/{r['id']}").json()
    assert [q["title"] for q in detail["questions"]] == ["지원 동기", "성장 과정"]
    assert detail["questions"][0]["char_limit"] == 1000

    assert alice.delete(f"/resumes/{r['id']}/questions/{q2['id']}").status_code == 204
    assert [q["id"] for q in alice.get(f"/resumes/{r['id']}").json()["questions"]] == [q1["id"]]


# --- 버전 -------------------------------------------------------------------

def test_every_save_creates_new_version(alice):
    r = _resume(alice)
    q = _question(alice, r["id"])
    v1 = _version(alice, r["id"], q["id"], "첫 번째 본문")
    v2 = _version(alice, r["id"], q["id"], "두 번째 본문입니다")
    assert (v1["version_no"], v2["version_no"]) == (1, 2)
    assert v2["source"] == "manual" and v2["char_count"] == len("두 번째 본문입니다")
    assert v1["over_limit"] is False

    timeline = alice.get(f"/resumes/{r['id']}/questions/{q['id']}/versions").json()
    assert [v["version_no"] for v in timeline] == [2, 1]
    assert "body" not in timeline[0]

    got = alice.get(f"/resumes/{r['id']}/questions/{q['id']}/versions/{v1['id']}").json()
    assert got["body"] == "첫 번째 본문"

    latest = alice.get(f"/resumes/{r['id']}").json()["questions"][0]["latest_version"]
    assert latest["version_no"] == 2


def test_client_cannot_set_source(alice):
    r = _resume(alice)
    q = _question(alice, r["id"])
    resp = alice.post(f"/resumes/{r['id']}/questions/{q['id']}/versions", json={"body": "x", "source": "ai"})
    assert resp.status_code == 422


def test_diff_between_versions(alice):
    r = _resume(alice)
    q = _question(alice, r["id"])
    _version(alice, r["id"], q["id"], "저는 백엔드 개발자입니다")
    _version(alice, r["id"], q["id"], "저는 성실한 백엔드 개발자입니다")
    d = alice.get(f"/resumes/{r['id']}/questions/{q['id']}/versions/diff", params={"from": 1, "to": 2}).json()
    inserted = "".join(s["after"] for s in d["segments"] if s["op"] == "insert")
    assert "성실한" in inserted
    assert alice.get(f"/resumes/{r['id']}/questions/{q['id']}/versions/diff",
                     params={"from": 1, "to": 9}).status_code == 404


def test_restore_creates_new_manual_version_with_origin(alice):
    r = _resume(alice)
    q = _question(alice, r["id"])
    v1 = _version(alice, r["id"], q["id"], "원래 문장")
    _version(alice, r["id"], q["id"], "바뀐 문장")
    restored = alice.post(f"/resumes/{r['id']}/questions/{q['id']}/versions/{v1['id']}/restore").json()
    assert restored["version_no"] == 3
    assert restored["body"] == "원래 문장"
    assert restored["source"] == "manual"
    assert restored["restored_from"] == v1["id"]


def test_ai_version_saved_through_service(alice):
    # A6(리라이팅)은 서비스 함수로 source="ai" 버전을 저장한다
    sub = f"svc-{uuid.uuid4()}"
    c = _client_for(sub)
    r = _resume(c)
    q = _question(c, r["id"])
    with SessionLocal() as db:
        version, _ = service.create_version(db, sub, uuid.UUID(r["id"]), uuid.UUID(q["id"]), "AI 후보", "ai")
        db.commit()
        assert version.source == "ai"


def test_over_limit_flag_after_50_versions(alice):
    r = _resume(alice)
    q = _question(alice, r["id"])
    for i in range(service.MAX_VERSIONS_PER_QUESTION):
        assert _version(alice, r["id"], q["id"], f"v{i}")["over_limit"] is False
    # 51번째도 저장은 된다(모든 저장은 새 버전). 압축 방식은 팀 확인 후 구현
    v51 = _version(alice, r["id"], q["id"], "v51")
    assert v51["version_no"] == 51 and v51["over_limit"] is True


def test_deleted_question_hides_versions(alice):
    r = _resume(alice)
    q = _question(alice, r["id"])
    v = _version(alice, r["id"], q["id"], "본문")
    alice.delete(f"/resumes/{r['id']}/questions/{q['id']}")
    assert alice.get(f"/resumes/{r['id']}/questions/{q['id']}/versions").status_code == 404
    assert alice.get(f"/resumes/{r['id']}/questions/{q['id']}/versions/{v['id']}").status_code == 404
    assert alice.post(f"/resumes/{r['id']}/questions/{q['id']}/versions", json={"body": "x"}).status_code == 404


# --- PII 처리 지점 연결 -----------------------------------------------------

def test_pii_hooks_wired_on_save_and_read(alice, monkeypatch):
    monkeypatch.setattr(pii_hooks, "tokenize_for_storage",
                        lambda owner, text: text.replace("010-1234-5678", "[PHONE_1]"))
    monkeypatch.setattr(pii_hooks, "restore_for_owner",
                        lambda owner, requester, text: text.replace("[PHONE_1]", "010-1234-5678"))
    r = _resume(alice)
    q = _question(alice, r["id"])
    v = _version(alice, r["id"], q["id"], "연락처 010-1234-5678")

    with SessionLocal() as db:
        stored = db.scalar(select(Version.body).where(Version.id == uuid.UUID(v["id"])))
    assert stored == "연락처 [PHONE_1]"          # DB에는 토큰화 상태
    assert v["body"] == "연락처 010-1234-5678"   # 본인 응답은 복원
    assert v["char_count"] == len("연락처 010-1234-5678")  # 글자 수는 원문 기준


# --- 소유자 격리 (IDOR) -----------------------------------------------------

def test_other_user_gets_404_everywhere(two_users):
    sw, a_sub, b_sub = two_users
    alice = sw.as_(a_sub)
    r = _resume(alice)
    q = _question(alice, r["id"])
    v = _version(alice, r["id"], q["id"], "앨리스의 본문")
    base = f"/resumes/{r['id']}"
    qbase = f"{base}/questions/{q['id']}"

    bob = sw.as_(b_sub)
    calls = [
        ("get", base, None),
        ("patch", base, {"title": "탈취"}),
        ("delete", base, None),
        ("post", f"{base}/questions", {"title": "x"}),
        ("patch", qbase, {"title": "x"}),
        ("delete", qbase, None),
        ("post", f"{qbase}/versions", {"body": "x"}),
        ("get", f"{qbase}/versions", None),
        ("get", f"{qbase}/versions/{v['id']}", None),
        ("get", f"{qbase}/versions/diff?from=1&to=1", None),
        ("post", f"{qbase}/versions/{v['id']}/restore", None),
    ]
    for method, url, body in calls:
        resp = getattr(bob, method)(url, **({"json": body} if body is not None else {}))
        assert resp.status_code == 404, (method, url, resp.status_code)
    assert bob.get("/resumes").json() == []

    alice = sw.as_(a_sub)
    detail = alice.get(base).json()
    assert detail["title"] == "네이버 백엔드"
    assert len(alice.get(f"{qbase}/versions").json()) == 1


def test_version_id_from_other_question_rejected(alice):
    r = _resume(alice)
    q1, q2 = _question(alice, r["id"], "q1"), _question(alice, r["id"], "q2")
    v = _version(alice, r["id"], q1["id"], "q1 본문")
    assert alice.get(f"/resumes/{r['id']}/questions/{q2['id']}/versions/{v['id']}").status_code == 404
    assert alice.post(f"/resumes/{r['id']}/questions/{q2['id']}/versions/{v['id']}/restore").status_code == 404
