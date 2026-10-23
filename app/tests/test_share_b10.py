"""B10 멘토 공유 API (spec 3.7, part2_guide 4.40)."""
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.auth import CurrentUser, Role, get_current_user
from app.core.errors import register_exception_handlers
from app.db import SessionLocal
from app.features.resumes.router import router as resumes_router
from app.features.share import index_hooks, period
from app.features.share.router import mentor_router, owner_router
from app.models import Resume, Share, User

# main.py(D 소유) 등록은 D에 요청. 테스트는 라우터를 테스트 앱에 직접 붙인다.
app = FastAPI()
register_exception_handlers(app)
for r in (resumes_router, owner_router, mentor_router):
    app.include_router(r)

PII = "010-1234-5678"


class As:
    def __init__(self, sub, role=Role.USER):
        self.sub, self.role = sub, role
        self.c = TestClient(app)

    def __getattr__(self, method):
        def call(*a, **kw):
            app.dependency_overrides[get_current_user] = lambda: CurrentUser(sub=self.sub, role=self.role)
            return getattr(self.c, method)(*a, **kw)
        return call


def _sub(p):
    return f"{p}-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def owner():
    return As(_sub("own"))


@pytest.fixture
def mentor():
    return As(_sub("men"), Role.MENTOR)


@pytest.fixture(autouse=True)
def hook_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(index_hooks, "sync_shared_with", lambda db, rid, sw: calls.append((rid, sw)))
    yield calls
    app.dependency_overrides.clear()


def _resume(owner, bodies=("본문",), title="자소서"):
    r = owner.post("/resumes", json={"title": title}).json()
    for i, b in enumerate(bodies):
        q = owner.post(f"/resumes/{r['id']}/questions", json={"title": f"문항{i}"}).json()
        owner.post(f"/resumes/{r['id']}/questions/{q['id']}/versions", json={"body": b})
    return r


def _share(owner, rid, mentor_sub, **kw):
    return owner.post(f"/resumes/{rid}/shares", json={"mentor_id": mentor_sub, **kw})


def _today():
    return period.today_kst(datetime.now(UTC))


def _expire(share_id):
    with SessionLocal.begin() as db:
        now = datetime.now(UTC)
        db.execute(update(Share).where(Share.id == uuid.UUID(share_id))
                   .values(created_at=now - timedelta(days=2), expires_at=now - timedelta(seconds=1)))


# --- 기간 ------------------------------------------------------------------

def test_period_midnight_kst_and_inclusive_30_days():
    end = date(2026, 11, 22)
    assert period.expires_at_for(end) == datetime(2026, 11, 22, 15, 0, tzinfo=UTC)  # 11/23 00:00 KST
    assert period.end_date_of(period.expires_at_for(end)) == end
    now = datetime(2026, 10, 23, 14, 40, tzinfo=UTC)  # 10/23 23:40 KST
    assert period.default_end(now) == date(2026, 10, 29)  # 공유일 포함 7일째
    assert period.max_end(now) == date(2026, 11, 21)      # 공유일 포함 30일째
    period.check_end(date(2026, 10, 23), now)
    period.check_end(date(2026, 11, 21), now)
    for bad in (date(2026, 10, 22), date(2026, 11, 22)):
        with pytest.raises(period.PeriodInvalid):
            period.check_end(bad, now)
    # 자정이 지나면 기준일이 바뀐다(UTC로는 같은 날)
    assert period.today_kst(datetime(2026, 10, 23, 15, 0, tzinfo=UTC)) == date(2026, 10, 24)
    assert period.iso_z(period.expires_at_for(end)) == "2026-11-22T15:00:00Z"


def test_create_default_7_days_and_sync(owner, mentor, hook_calls):
    r = _resume(owner)
    res = _share(owner, r["id"], mentor.sub)
    assert res.status_code == 201, res.text
    s = res.json()
    assert s["end_date"] == (_today() + timedelta(days=6)).isoformat() and s["status"] == "active"
    with SessionLocal() as db:
        sw = db.get(Resume, uuid.UUID(r["id"])).shared_with
    assert sw == [{"user_id": mentor.sub, "expires_at": period.iso_z(period.expires_at_for(_today() + timedelta(days=6)))}]
    assert hook_calls[-1] == (uuid.UUID(r["id"]), sw)


@pytest.mark.parametrize("days,ok", [(0, True), (29, True), (30, False), (-1, False)])
def test_create_period_bounds(owner, mentor, days, ok):
    r = _resume(owner)
    res = _share(owner, r["id"], mentor.sub, end_date=(_today() + timedelta(days=days)).isoformat())
    assert res.status_code == (201 if ok else 422), res.text


# --- 멘토 열람 --------------------------------------------------------------

def test_mentor_sees_snapshot_tokenized_readonly(owner, mentor):
    r = _resume(owner, bodies=(f"연락처 {PII}",))
    s = _share(owner, r["id"], mentor.sub).json()
    q = owner.get(f"/resumes/{r['id']}").json()["questions"][0]
    owner.post(f"/resumes/{r['id']}/questions/{q['id']}/versions", json={"body": "공유 후 수정본"})

    assert [x["id"] for x in mentor.get("/mentor/shares").json()] == [s["id"]]
    view = mentor.get(f"/mentor/shares/{s['id']}").json()
    assert view["resume_title"] == "자소서"
    assert [x["body"] for x in view["questions"]] == ["연락처 [[PHONE_1]]"]  # 공유 시점 버전, 토큰 상태
    assert view["questions"][0]["version_no"] == 1


def test_mentor_endpoints_require_mentor_role_and_target(owner, mentor):
    r = _resume(owner)
    s = _share(owner, r["id"], mentor.sub).json()
    as_user = As(mentor.sub, Role.USER)
    assert as_user.get("/mentor/shares").status_code == 403
    other_mentor = As(_sub("men"), Role.MENTOR)
    assert other_mentor.get(f"/mentor/shares/{s['id']}").status_code == 404
    assert other_mentor.get("/mentor/shares").json() == []


def test_deleted_question_hidden_and_deleted_resume_404(owner, mentor):
    r = _resume(owner, bodies=("a", "b"))
    s = _share(owner, r["id"], mentor.sub).json()
    q0 = owner.get(f"/resumes/{r['id']}").json()["questions"][0]
    owner.delete(f"/resumes/{r['id']}/questions/{q0['id']}")
    assert [x["body"] for x in mentor.get(f"/mentor/shares/{s['id']}").json()["questions"]] == ["b"]
    owner.delete(f"/resumes/{r['id']}")
    assert mentor.get(f"/mentor/shares/{s['id']}").status_code == 404
    assert mentor.get("/mentor/shares").json() == []


# --- 다시 공유(확인 문구) ----------------------------------------------------

def test_reshare_same_content_requires_confirm_then_replaces(owner, mentor):
    r = _resume(owner)
    first = _share(owner, r["id"], mentor.sub).json()
    res = _share(owner, r["id"], mentor.sub)
    assert res.status_code == 409
    body = res.json()
    assert body["code"] == "share_confirm_required" and body["errors"] == {"kind": "same_content"}
    assert "같은 내용" in body["detail"]

    second = _share(owner, r["id"], mentor.sub, confirm=True).json()
    shares = {x["id"]: x["status"] for x in owner.get(f"/resumes/{r['id']}/shares").json()}
    assert shares == {first["id"]: "revoked", second["id"]: "active"}
    assert mentor.get(f"/mentor/shares/{first['id']}").status_code == 404
    with SessionLocal() as db:
        assert len(db.get(Resume, uuid.UUID(r["id"])).shared_with) == 1


def test_reshare_after_new_version_says_older_version(owner, mentor):
    r = _resume(owner)
    _share(owner, r["id"], mentor.sub)
    q = owner.get(f"/resumes/{r['id']}").json()["questions"][0]
    owner.post(f"/resumes/{r['id']}/questions/{q['id']}/versions", json={"body": "새 버전"})
    res = _share(owner, r["id"], mentor.sub)
    assert res.json()["errors"] == {"kind": "older_version"} and "이전 버전" in res.json()["detail"]


def test_share_other_resume_to_same_mentor_keeps_both(owner, mentor):
    r1, r2 = _resume(owner, title="A"), _resume(owner, title="B")
    a = _share(owner, r1["id"], mentor.sub).json()
    res = _share(owner, r2["id"], mentor.sub)
    assert res.json()["errors"] == {"kind": "other_resume"} and "별개로" in res.json()["detail"]
    b = _share(owner, r2["id"], mentor.sub, confirm=True).json()
    assert {x["id"] for x in mentor.get("/mentor/shares").json()} == {a["id"], b["id"]}


@pytest.mark.parametrize("end_it", ["expire", "revoke"])
def test_ended_share_does_not_need_confirm_and_is_new(owner, mentor, end_it):
    r = _resume(owner)
    first = _share(owner, r["id"], mentor.sub).json()
    if end_it == "expire":
        _expire(first["id"])
    else:
        assert owner.delete(f"/shares/{first['id']}").status_code == 204
    res = _share(owner, r["id"], mentor.sub)
    assert res.status_code == 201 and res.json()["id"] != first["id"]
    assert mentor.get(f"/mentor/shares/{first['id']}").status_code == 404


# --- 연장·취소 --------------------------------------------------------------

def test_extend_counts_from_extension_day(owner, mentor, hook_calls):
    r = _resume(owner)
    s = _share(owner, r["id"], mentor.sub, end_date=_today().isoformat()).json()
    new_end = _today() + timedelta(days=29)
    res = owner.post(f"/shares/{s['id']}/extend", json={"end_date": new_end.isoformat()})
    assert res.status_code == 200 and res.json()["end_date"] == new_end.isoformat()
    assert hook_calls[-1][1][0]["expires_at"] == period.iso_z(period.expires_at_for(new_end))
    too_far = owner.post(f"/shares/{s['id']}/extend", json={"end_date": (_today() + timedelta(days=30)).isoformat()})
    assert too_far.status_code == 422
    not_later = owner.post(f"/shares/{s['id']}/extend", json={"end_date": new_end.isoformat()})
    assert not_later.status_code == 422 and "뒤여야" in not_later.json()["detail"]


@pytest.mark.parametrize("end_it", ["expire", "revoke"])
def test_cannot_extend_ended_share(owner, mentor, end_it):
    r = _resume(owner)
    s = _share(owner, r["id"], mentor.sub).json()
    _expire(s["id"]) if end_it == "expire" else owner.delete(f"/shares/{s['id']}")
    res = owner.post(f"/shares/{s['id']}/extend", json={"end_date": _today().isoformat()})
    assert res.status_code == 409


def test_revoke_removes_access_and_sync(owner, mentor, hook_calls):
    r = _resume(owner)
    s = _share(owner, r["id"], mentor.sub).json()
    assert owner.delete(f"/shares/{s['id']}").status_code == 204
    assert owner.delete(f"/shares/{s['id']}").status_code == 204  # 멱등
    assert mentor.get(f"/mentor/shares/{s['id']}").status_code == 404
    with SessionLocal() as db:
        assert db.get(Resume, uuid.UUID(r["id"])).shared_with == []
    assert hook_calls[-1] == (uuid.UUID(r["id"]), [])


def test_other_user_cannot_touch_shares(owner, mentor):
    r = _resume(owner)
    s = _share(owner, r["id"], mentor.sub).json()
    other = As(_sub("own"))
    assert _share(other, r["id"], mentor.sub).status_code == 404
    assert other.get(f"/resumes/{r['id']}/shares").status_code == 404
    assert other.post(f"/shares/{s['id']}/extend", json={"end_date": _today().isoformat()}).status_code == 404
    assert other.delete(f"/shares/{s['id']}").status_code == 404
    assert mentor.get(f"/mentor/shares/{s['id']}").status_code == 200


# --- 입력 검증 --------------------------------------------------------------

def test_mentor_row_created_if_missing(owner):
    r = _resume(owner)
    new_mentor = _sub("men")
    assert _share(owner, r["id"], new_mentor).status_code == 201
    with SessionLocal() as db:
        assert db.get(User, new_mentor) is not None


def test_rejects_self_deleted_mentor_and_empty_resume(owner, mentor):
    r = _resume(owner)
    assert _share(owner, r["id"], owner.sub).status_code == 422
    with SessionLocal.begin() as db:
        db.add(User(id=mentor.sub, deleted_at=datetime.now(UTC)))
    assert _share(owner, r["id"], mentor.sub).status_code == 422
    empty = owner.post("/resumes", json={"title": "빈 자소서"}).json()
    assert _share(owner, empty["id"], _sub("men")).status_code == 422


def test_server_only_fields_rejected(owner, mentor):
    r = _resume(owner)
    res = _share(owner, r["id"], mentor.sub, version_ids=[], expires_at="2030-01-01T00:00:00Z")
    assert res.status_code == 422
