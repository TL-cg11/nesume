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
    kw.setdefault("mentor_label", "김멘토")
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
    assert [x["body"] for x in view["questions"]] == ["연락처 (전화번호 비공개)"]  # 공유 시점 버전, 비공개 문구
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


# --- 공유 버전 태그·멘토 별칭 (part2_guide 4.43) ------------------------------

@pytest.mark.parametrize("label", [None, "", "   ", "가" * 21, "주민 900101-1234567"])
def test_mentor_label_required_and_validated(owner, mentor, label):
    r = _resume(owner)
    body = {"mentor_id": mentor.sub} if label is None else {"mentor_id": mentor.sub, "mentor_label": label}
    assert owner.post(f"/resumes/{r['id']}/shares", json=body).status_code == 422


def test_rename_label_including_ended_share(owner, mentor):
    r = _resume(owner)
    s = _share(owner, r["id"], mentor.sub, mentor_label="  김멘토  ").json()
    assert s["mentor_label"] == "김멘토"
    owner.delete(f"/shares/{s['id']}")
    res = owner.patch(f"/shares/{s['id']}", json={"mentor_label": "학교 취업센터"})
    assert res.status_code == 200 and res.json()["mentor_label"] == "학교 취업센터"
    assert As(_sub("own")).patch(f"/shares/{s['id']}", json={"mentor_label": "x"}).status_code == 404
    assert owner.patch(f"/shares/{s['id']}", json={"mentor_label": ""}).status_code == 422


def test_label_not_shown_to_mentor(owner, mentor):
    r = _resume(owner)
    s = _share(owner, r["id"], mentor.sub, mentor_label="비밀 메모").json()
    assert "비밀 메모" not in mentor.get("/mentor/shares").text
    assert "비밀 메모" not in mentor.get(f"/mentor/shares/{s['id']}").text


def _versions(owner, r, include_ended=False):
    q = owner.get(f"/resumes/{r['id']}").json()["questions"][0]
    url = f"/resumes/{r['id']}/questions/{q['id']}/versions" + ("?include_ended=true" if include_ended else "")
    return {v["version_no"]: v["shares"] for v in owner.get(url).json()}, q


def test_version_tags_per_version_and_mentor(owner, mentor):
    r = _resume(owner)
    m2, m3 = _sub("men"), _sub("men")
    _share(owner, r["id"], mentor.sub, mentor_label="김멘토", end_date=(_today() + timedelta(days=6)).isoformat())
    _share(owner, r["id"], m2, mentor_label="박멘토", end_date=(_today() + timedelta(days=3)).isoformat())
    tags, q = _versions(owner, r)
    assert [t["mentor_label"] for t in tags[1]] == ["박멘토", "김멘토"]  # 종료일 빠른 순
    assert all(t["status"] == "active" and t["ended_on"] is None for t in tags[1])

    owner.post(f"/resumes/{r['id']}/questions/{q['id']}/versions", json={"body": "v2"})
    _share(owner, r["id"], m3, mentor_label="이멘토")
    tags, _ = _versions(owner, r)
    assert [t["mentor_label"] for t in tags[2]] == ["이멘토"]
    assert len(tags[1]) == 2


def test_ended_shares_hidden_by_default_and_shown_on_request(owner, mentor):
    r = _resume(owner)
    revoked = _share(owner, r["id"], mentor.sub, mentor_label="취소멘토").json()
    owner.delete(f"/shares/{revoked['id']}")
    expired = _share(owner, r["id"], _sub("men"), mentor_label="만료멘토").json()
    _expire(expired["id"])
    _share(owner, r["id"], _sub("men"), mentor_label="유효멘토")

    tags, _ = _versions(owner, r)
    assert [t["mentor_label"] for t in tags[1]] == ["유효멘토"]
    tags, _ = _versions(owner, r, include_ended=True)
    by = {t["mentor_label"]: t for t in tags[1]}
    assert [t["mentor_label"] for t in tags[1]][0] == "유효멘토"  # 유효한 공유가 앞
    assert by["취소멘토"]["status"] == "revoked" and by["취소멘토"]["ended_on"] == _today().isoformat()
    assert by["만료멘토"]["status"] == "expired" and by["만료멘토"]["ended_on"] is not None


def test_resume_list_and_detail_share_summary(owner, mentor):
    r1, r2 = _resume(owner, title="A"), _resume(owner, title="B")
    _share(owner, r1["id"], mentor.sub, end_date=(_today() + timedelta(days=9)).isoformat())
    _share(owner, r1["id"], _sub("men"), end_date=(_today() + timedelta(days=2)).isoformat())
    gone = _share(owner, r1["id"], _sub("men")).json()
    owner.delete(f"/shares/{gone['id']}")
    summary = {x["title"]: x["share_summary"] for x in owner.get("/resumes").json()}
    assert summary["A"] == {"active_count": 2, "earliest_end_date": (_today() + timedelta(days=2)).isoformat()}
    assert summary["B"] is None
    assert owner.get(f"/resumes/{r1['id']}").json()["share_summary"]["active_count"] == 2


def test_readable_token_text():
    from app.features.share.display import readable
    assert readable("[[PERSON_1]]님 연락처 [[PHONE_2]], [[EMAIL_1]] / [[ADDRESS_1]]") == (
        "(이름 비공개)님 연락처 (전화번호 비공개), (이메일 비공개) / (주소 비공개)")
    assert readable("[[ORG_1]]·[[SCHOOL_3]]·[[NEWKIND_1]]") == "(기관명 비공개)·(학교명 비공개)·(비공개 정보)"
    assert readable("토큰 없음 [[x]] [[PHONE]]") == "토큰 없음 [[x]] [[PHONE]]"


# --- 권한 없는 열람 시도 감시: 10분 내 5회 → 감사 로그 1행 (4.57) ---------------

def _deny_logs(mentor_sub):
    from sqlalchemy import select

    from app.models import AuditLog
    with SessionLocal() as db:
        return db.scalars(select(AuditLog).where(AuditLog.user_id == mentor_sub,
                                                 AuditLog.feature == "share.view")).all()


def test_denied_views_logged_once_at_fifth_attempt(owner, mentor):
    r = _resume(owner)
    s = _share(owner, r["id"], mentor.sub).json()
    _expire(s["id"])
    for i in range(4):
        assert mentor.get(f"/mentor/shares/{s['id']}").status_code == 404
    assert _deny_logs(mentor.sub) == []  # 4회까지는 기록 안 함
    assert mentor.get(f"/mentor/shares/{s['id']}").status_code == 404  # 5회째도 응답은 그대로 404
    logs = _deny_logs(mentor.sub)
    assert len(logs) == 1
    log = logs[0]
    assert (log.decision, log.query_type, log.flags, log.rule_id, log.role) == (
        "block", "out_of_scope", ["SHARE_DENIED_BURST"], "SHARE-DENY-001", "mentor")
    for _ in range(4):
        mentor.get(f"/mentor/shares/{s['id']}")
    assert len(_deny_logs(mentor.sub)) == 1  # 같은 구간에서는 한 번만


def test_denied_comment_attempts_and_unknown_ids_counted(owner, mentor):
    r = _resume(owner)
    s = _share(owner, r["id"], mentor.sub).json()
    owner.delete(f"/shares/{s['id']}")  # 취소
    for _ in range(3):
        mentor.post(f"/mentor/shares/{s['id']}/comments", json={"version_id": str(uuid.uuid4()),
                                                                "paragraph_index": 0, "body": "x"})
    for _ in range(2):
        mentor.get(f"/mentor/shares/{uuid.uuid4()}")  # 없는 공유 ID 찌르기
    assert len(_deny_logs(mentor.sub)) == 1


def test_valid_views_and_other_mentors_not_counted(owner, mentor):
    r = _resume(owner)
    s = _share(owner, r["id"], mentor.sub).json()
    for _ in range(6):
        assert mentor.get(f"/mentor/shares/{s['id']}").status_code == 200
    other = As(_sub("men"), Role.MENTOR)
    for _ in range(4):
        other.get(f"/mentor/shares/{s['id']}")
    assert _deny_logs(mentor.sub) == [] and _deny_logs(other.sub) == []


def test_new_window_counts_again():
    from app.auth import CurrentUser
    from app.features.share import denials

    u = CurrentUser(sub=_sub("men"), role=Role.MENTOR)
    t0 = 1_000_000.0
    assert [denials.record_denied(u, now=t0 + i) for i in range(5)] == [False] * 4 + [True]
    assert denials.record_denied(u, now=t0 + 10) is False
    later = t0 + denials.WINDOW_SECONDS + 1  # 10분이 지나면 새로 셈
    assert [denials.record_denied(u, now=later + i) for i in range(5)][-1] is True
    assert len(_deny_logs(u.sub)) == 2
