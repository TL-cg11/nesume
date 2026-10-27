"""B9 프롬프트 템플릿 (spec 3.6, part2_guide 4.52)."""
import time
import uuid

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.auth import CurrentUser, Role, get_current_user
from app.auth import mfa
from app.config import get_settings
from app.core.errors import register_exception_handlers
from app.db import SessionLocal
from app.features.templates import service
from app.features.templates.router import router
from app.models import PromptTemplate

app = FastAPI()
register_exception_handlers(app)
app.include_router(router)  # main.py(D 소유) 등록 전이라 테스트 앱에 붙인다

ROLES = {"user": Role.USER, "mentor": Role.MENTOR, "operator": Role.OPERATOR, "system": Role.SYSTEM}


@pytest.fixture
def client(monkeypatch):
    sub = {r: f"tpl-{r}-{uuid.uuid4().hex[:6]}" for r in ROLES}

    def current(request: Request):
        role = request.headers.get("X-Role", "operator")
        return CurrentUser(sub=sub[role], role=ROLES[role], auth_time=int(time.time()))

    app.dependency_overrides[get_current_user] = current
    mfa_on = {"required": False}
    app.dependency_overrides[get_settings] = lambda: get_settings().model_copy(
        update={"operator_mfa_required": mfa_on["required"]})
    c = TestClient(app)
    c.mfa = mfa_on
    yield c
    app.dependency_overrides.clear()


def _name():
    return f"rewrite-{uuid.uuid4().hex[:8]}"


BODY = "다음 글을 {{tone}} 톤으로 {{length}}자 안에 다듬어 주세요. 예시 JSON {\"a\": 1}"


def _create(c, name, **kw):
    return c.post("/templates", json={"name": name, "purpose": "rewrite", "body": BODY,
                                      "variables": ["tone", "length"], **kw})


def test_create_new_version_activate_flow(client):
    name = _name()
    v1 = _create(client, name)
    assert v1.status_code == 201, v1.text
    assert (v1.json()["version"], v1.json()["is_active"]) == (1, False)
    v2 = client.post(f"/templates/{name}/versions", json={"body": "{{tone}} 톤으로", "variables": ["tone"]}).json()
    assert v2["version"] == 2 and v2["purpose"] == "rewrite" and not v2["is_active"]
    assert client.put(f"/templates/{v1.json()['id']}/activate").json()["is_active"]
    assert client.put(f"/templates/{v2['id']}/activate").json()["is_active"]
    versions = client.get(f"/templates/{name}/versions").json()
    assert [(v["version"], v["is_active"]) for v in versions] == [(2, True), (1, False)]  # 활성은 1개
    summary = next(s for s in client.get("/templates").json() if s["name"] == name)
    assert summary == {"name": name, "purpose": "rewrite", "latest_version": 2, "active_version": 2}
    with SessionLocal() as db:
        assert {t.grade for t in db.query(PromptTemplate).filter_by(name=name)} == {"internal"}  # B8
        assert db.query(PromptTemplate).filter_by(name=name, version=1).one().body == BODY  # 덮어쓰지 않음


def test_duplicate_name_and_unknown(client):
    name = _name()
    _create(client, name)
    assert _create(client, name).json()["code"] == "template_exists"
    assert client.post(f"/templates/{_name()}/versions", json={"body": "x"}).status_code == 404
    assert client.get(f"/templates/{_name()}/versions").status_code == 404
    assert client.put(f"/templates/{uuid.uuid4()}/activate").status_code == 404


@pytest.mark.parametrize("body,variables,missing,unused", [
    ("{{tone}} 그리고 {{length}}", ["tone"], ["length"], []),
    ("{{tone}}", ["tone", "length"], [], ["length"]),
    ("{{tone}}", ["tone", "tone"], [], []),  # 중복 선언
])
def test_variables_must_match(client, body, variables, missing, unused):
    res = client.post("/templates", json={"name": _name(), "purpose": "rewrite", "body": body, "variables": variables})
    assert res.status_code == 422 and res.json()["code"] == "template_variables_mismatch"
    assert res.json()["errors"] == {"missing": missing, "unused": unused}


@pytest.mark.parametrize("role", ["user", "mentor", "system"])
def test_non_operator_forbidden(client, role):
    name = _name()
    t = _create(client, name).json()
    h = {"X-Role": role}
    assert client.get("/templates", headers=h).status_code == 403
    assert _create(client, _name(), **{}).status_code == 201  # 운영자는 됨(대조)
    assert client.post("/templates", headers=h, json={"name": _name(), "purpose": "x", "body": "a"}).status_code == 403
    assert client.post(f"/templates/{name}/versions", headers=h, json={"body": "a"}).status_code == 403
    assert client.get(f"/templates/{name}/versions", headers=h).status_code == 403
    assert client.put(f"/templates/{t['id']}/activate", headers=h).status_code == 403  # C11-AUTHZ-07


def test_activate_requires_mfa_session(client, monkeypatch):
    t = _create(client, _name()).json()
    client.mfa["required"] = True
    monkeypatch.setattr(mfa, "totp_enrolled", lambda sub: False)
    res = client.put(f"/templates/{t['id']}/activate")
    assert res.status_code == 403 and res.json()["code"] == "mfa_required"
    assert client.post("/templates", json={"name": _name(), "purpose": "x", "body": "a"}).status_code == 201  # 작성은 MFA 불필요
    monkeypatch.setattr(mfa, "totp_enrolled", lambda sub: True)
    assert client.put(f"/templates/{t['id']}/activate").status_code == 200


def test_server_only_fields_rejected(client):
    res = client.post("/templates", json={"name": _name(), "purpose": "x", "body": "a", "version": 9,
                                          "is_active": True})
    assert res.status_code == 422


def test_reader_for_a_returns_only_active_and_renders(client):
    name = _name()
    v1 = _create(client, name).json()
    with SessionLocal() as db:
        assert service.get_active_template(db, name) is None  # 활성 버전 없음
    client.put(f"/templates/{v1['id']}/activate")
    client.post(f"/templates/{name}/versions", json={"body": "새 버전 {{tone}}", "variables": ["tone"]})
    with SessionLocal() as db:
        t = service.get_active_template(db, name)
    assert t.version == 1 and t.variables == ("tone", "length")  # 새 버전은 활성 전환 전까지 안 보임
    out = service.render(t, {"tone": "정중한", "length": "500"})
    assert out.startswith("다음 글을 정중한 톤으로 500자") and '{"a": 1}' in out  # 일반 중괄호는 그대로
    for bad in ({"tone": "x"}, {"tone": "x", "length": "1", "extra": "y"}):
        with pytest.raises(service.RenderValuesMismatch):
            service.render(t, bad)
