"""B19 멘토 공유 우회 시나리오: 형식 검사 + api 경로 실제 투입 (part2_guide 4.46).

평가셋은 저장소 최상위 `eval/scenarios/`(B 소유)에 있고 `/eval`로 마운트돼야 읽힌다(D 요청 중).
llm 경로는 가드레일·C6 검색을 거치므로 B16 평가 러너에서 측정한다.
"""
import os
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.auth import CurrentUser, Role, get_current_user
from app.core.errors import register_exception_handlers
from app.db import SessionLocal
from app.features.resumes.router import router as resumes_router
from app.features.share import index_hooks
from app.features.share.router import mentor_router, owner_router
from app.models import Share

FILE = Path(os.environ.get("EVAL_DIR", "/eval")) / "scenarios" / "b19_share.yaml"
pytestmark = pytest.mark.skipif(not FILE.exists(), reason="eval/ 미마운트(D 요청 중)")

ID = re.compile(r"^B19-SHARE-\d{2}$")
DECISIONS = {"allow", "block", "mask"}
EXCLUDE_TARGETS = {"unshared_resume", "post_share_version"}

app = FastAPI()
register_exception_handlers(app)
for r in (resumes_router, owner_router, mentor_router):
    app.include_router(r)


def _load():
    with open(FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)["scenarios"]


SCENARIOS = _load() if FILE.exists() else []
API = [s for s in SCENARIOS if s["channel"] == "api"]


# --- 형식 --------------------------------------------------------------------

def test_counts_and_ids():
    assert len(SCENARIOS) == 5
    assert [s["id"] for s in SCENARIOS] == [f"B19-SHARE-{i:02d}" for i in range(1, 6)]
    assert {s["channel"] for s in SCENARIOS} == {"api", "llm"}


def test_well_formed():
    for s in SCENARIOS:
        assert ID.match(s["id"]) and s["category"] == "share_bypass", s["id"]
        assert s["role"] == "mentor" and s["feature"] and s.get("note"), s["id"]
        assert s["expect"]["decision"] in DECISIONS, s["id"]
        assert s["preconditions"]["share_state"] in {"active", "expired", "revoked"}, s["id"]
        if s["channel"] == "api":
            assert s["request"]["method"] in {"GET", "POST", "PATCH", "DELETE"}, s["id"]
            assert s["request"]["path"].startswith("/") and "turns" not in s, s["id"]
            assert s["expect"]["decision"] == "block" and s["expect"]["http_status"] in {403, 404}, s["id"]
        else:
            assert s["turns"] and "request" not in s, s["id"]
            assert set(s["expect"]["retrieval_excludes"]) <= EXCLUDE_TARGETS, s["id"]


# --- api 경로 실제 투입 ----------------------------------------------------------

class _As:
    def __init__(self, sub, role):
        self.sub, self.role, self.c = sub, role, TestClient(app)

    def call(self, method, path, **kw):
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(sub=self.sub, role=self.role)
        return self.c.request(method, path, **kw)


@pytest.fixture(autouse=True)
def _no_vector_sync(monkeypatch):
    monkeypatch.setattr(index_hooks, "sync_shared_with", lambda *a, **k: None)
    yield
    app.dependency_overrides.clear()


def _seed(state):
    """작성자·멘토·자소서 A(문항 1, v1) + 멘토 공유를 시나리오 상태로 만든다."""
    owner = _As(f"b19o-{uuid.uuid4().hex[:8]}", Role.USER)
    mentor = _As(f"b19m-{uuid.uuid4().hex[:8]}", Role.MENTOR)
    r = owner.call("POST", "/resumes", json={"title": "A"}).json()
    q = owner.call("POST", f"/resumes/{r['id']}/questions", json={"title": "q"}).json()
    owner.call("POST", f"/resumes/{r['id']}/questions/{q['id']}/versions", json={"body": "v1"})
    s = owner.call("POST", f"/resumes/{r['id']}/shares",
                   json={"mentor_id": mentor.sub, "mentor_label": "멘토"}).json()
    if state == "revoked":
        owner.call("DELETE", f"/shares/{s['id']}")
    elif state == "expired":
        now = datetime.now(UTC)
        with SessionLocal.begin() as db:
            db.execute(update(Share).where(Share.id == uuid.UUID(s["id"]))
                       .values(created_at=now - timedelta(days=2), expires_at=now - timedelta(seconds=1)))
    return mentor, {"share_id": s["id"], "resume_id": r["id"], "question_id": q["id"]}, owner


@pytest.mark.parametrize("s", API, ids=[s["id"] for s in API])
def test_api_scenario(s):
    mentor, ids, owner = _seed(s["preconditions"]["share_state"])
    req = s["request"]
    res = mentor.call(req["method"], req["path"].format(**ids), json=req.get("body"))
    assert res.status_code == s["expect"]["http_status"], f"{s['id']}: {res.status_code} {res.text}\n  {s['note']}"
    # 차단됐으면 작성자 데이터도 그대로여야 한다(편집 시도가 반영되지 않음)
    versions = owner.call("GET", f"/resumes/{ids['resume_id']}/questions/{ids['question_id']}/versions").json()
    assert [v["version_no"] for v in versions] == [1]


def test_active_share_is_viewable_control():
    """대조군: 유효한 공유는 열람된다(시나리오가 '항상 404'로 통과하는 것을 막는다)."""
    mentor, ids, _ = _seed("active")
    assert mentor.call("GET", f"/mentor/shares/{ids['share_id']}").status_code == 200
