"""멘토 공유: 공유할 문항·버전 선택 + 이메일로 멘토 지정(B10 후속, 10/29)."""
import pytest

from app.auth import Role
from app.auth.admin_router import get_cognito_client
from app.features.share import directory
from tests.test_share_b10 import As, _resume, _share, _sub, app, hook_calls  # noqa: F401  (hook_calls: autouse 픽스처)


class FakeIdp:
    """cognito-idp 대역: email·sub 필터 ListUsers, 그룹 조회."""

    def __init__(self, users):  # users: [(email, sub, groups)]
        self.users = users

    def list_users(self, UserPoolId, Filter, Limit):  # noqa: N803 (boto3 인자 이름)
        key, value = Filter.split(" = ")
        value = value.strip('"')
        hit = [u for u in self.users if (u[0] if key == "email" else u[1]) == value]
        attrs = lambda u: [{"Name": "email", "Value": u[0]}, {"Name": "sub", "Value": u[1]}]  # noqa: E731
        return {"Users": [{"Username": u[0], "Attributes": attrs(u)} for u in hit[:Limit]]}

    def admin_list_groups_for_user(self, UserPoolId, Username):  # noqa: N803
        u = next(u for u in self.users if u[0] == Username)
        return {"Groups": [{"GroupName": g} for g in u[2]]}


@pytest.fixture
def owner():
    return As(_sub("own"))


@pytest.fixture
def mentor():
    return As(_sub("men"), Role.MENTOR)


@pytest.fixture(autouse=True)
def _pool(monkeypatch):
    monkeypatch.setattr(directory, "_pool", lambda: "local_test")


def _versions(owner, rid):
    detail = owner.get(f"/resumes/{rid}").json()
    out = {}
    for q in detail["questions"]:
        out[q["id"]] = owner.get(f"/resumes/{rid}/questions/{q['id']}/versions").json()  # 최신이 앞
    return detail, out


# --- 이메일로 멘토 찾기 ---------------------------------------------------------

def test_find_mentor_sub_only_for_mentor_group():
    idp = FakeIdp([("m@x.com", "sub-m", ["mentor"]), ("u@x.com", "sub-u", [])])
    assert directory.find_mentor_sub(idp, " M@X.com ") == "sub-m"
    assert directory.find_mentor_sub(idp, "u@x.com") is None, "멘토 그룹이 아니면 공유 불가"
    assert directory.find_mentor_sub(idp, "none@x.com") is None
    assert directory.find_mentor_sub(idp, 'a" or sub = "x') is None, "필터 문자열 주입 차단"


def test_emails_for_skips_unknown_and_bad_ids():
    idp = FakeIdp([("m@x.com", "sub-m", ["mentor"])])
    assert directory.emails_for(idp, ["sub-m", "sub-m", "gone", 'x" or "1']) == {"sub-m": "m@x.com"}


def test_share_by_email_reaches_mentor(owner, mentor):
    idp = FakeIdp([("mentor@x.com", mentor.sub, ["mentor"]), ("user@x.com", _sub("u"), [])])
    app.dependency_overrides[get_cognito_client] = lambda: idp
    r = _resume(owner)
    body = {"mentor_label": "김멘토"}
    res = owner.post(f"/resumes/{r['id']}/shares", json={"mentor_email": "mentor@x.com", **body})
    assert res.status_code == 201, res.text
    assert [s["id"] for s in mentor.get("/mentor/shares").json()] == [res.json()["id"]]
    bad = owner.post(f"/resumes/{r['id']}/shares", json={"mentor_email": "user@x.com", **body})
    assert bad.status_code == 422 and "멘토 계정을 찾을 수 없습니다" in bad.json()["detail"]


# --- 공유할 문항·버전 고르기 ------------------------------------------------------

def test_share_selected_questions_and_older_version(owner, mentor):
    r = _resume(owner, bodies=("1번 v1", "2번 v1"))
    detail, vers = _versions(owner, r["id"])
    q1, q2 = detail["questions"]
    owner.post(f"/resumes/{r['id']}/questions/{q1['id']}/versions", json={"body": "1번 v2"})
    _, vers = _versions(owner, r["id"])
    v1_of_q1 = vers[q1["id"]][-1]["id"]  # 예전 버전
    res = _share(owner, r["id"], mentor.sub, version_ids=[v1_of_q1])  # 1번 문항만, 예전 버전으로
    assert res.status_code == 201, res.text
    seen = mentor.get(f"/mentor/shares/{res.json()['id']}").json()
    assert [(q["question_title"], q["body"]) for q in seen["questions"]] == [(q1["title"], "1번 v1")]


def test_share_rejects_two_versions_of_one_question_or_other_resume(owner, mentor):
    r = _resume(owner, bodies=("본문",))
    other = _resume(owner, bodies=("다른 자소서",), title="다른")
    detail, vers = _versions(owner, r["id"])
    q = detail["questions"][0]
    owner.post(f"/resumes/{r['id']}/questions/{q['id']}/versions", json={"body": "본문 v2"})
    _, vers = _versions(owner, r["id"])
    two = [v["id"] for v in vers[q["id"]]]
    assert _share(owner, r["id"], mentor.sub, version_ids=two).status_code == 422
    _, other_vers = _versions(owner, other["id"])
    foreign = next(iter(other_vers.values()))[0]["id"]
    assert _share(owner, r["id"], mentor.sub, version_ids=[foreign]).status_code == 422
    assert _share(owner, r["id"], mentor.sub, version_ids=[]).status_code == 422, "아무것도 고르지 않음"


def test_mentor_role_fixture_is_mentor(mentor):
    assert mentor.role is Role.MENTOR


def test_emails_shown_to_owner_and_mentor(owner, mentor):
    """작성자 공유 목록엔 멘토 이메일, 멘토 받은 공유엔 작성자 이메일(10/29). Cognito가 없으면 비움."""
    idp = FakeIdp([("own@x.com", owner.sub, []), ("men@x.com", mentor.sub, ["mentor"])])
    app.dependency_overrides[get_cognito_client] = lambda: idp
    r = _resume(owner)
    assert _share(owner, r["id"], mentor.sub).status_code == 201
    assert [s["mentor_email"] for s in owner.get(f"/resumes/{r['id']}/shares").json()] == ["men@x.com"]
    got = mentor.get("/mentor/shares").json()
    assert got[0]["owner_email"] == "own@x.com" and got[0]["shared_at"]


def test_emails_blank_without_directory(owner, mentor, monkeypatch):
    def no_pool():
        raise directory.DirectoryUnavailable()
    monkeypatch.setattr(directory, "_pool", no_pool)
    r = _resume(owner)
    _share(owner, r["id"], mentor.sub)
    assert owner.get(f"/resumes/{r['id']}/shares").json()[0]["mentor_email"] is None
    assert mentor.get("/mentor/shares").json()[0]["owner_email"] is None
