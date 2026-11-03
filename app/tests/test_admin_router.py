"""D6 운영자 역할 변경 API 단위 테스트. Cognito 는 가짜 클라이언트로 대체한다."""
import time
import uuid
from datetime import UTC, datetime

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.auth.admin_router import get_cognito_client
from app.auth.cognito import TokenVerifier, get_token_verifier
from app.db import get_db
from app.main import app
from app.models import User

ISSUER = "https://issuer.test/pool"
CLIENT_ID = "test-client"


class FakeIdp:
    """AWS(username == sub) 모드의 cognito-idp 흉내. 호출 기록을 남긴다."""

    def __init__(self, groups: dict[str, set[str]], emails: dict[str, str] | None = None):
        self.groups = groups  # username -> group set
        self.emails = emails or {}  # username -> email
        self.signed_out: list[str] = []
        self.filters: list[str] = []

    def _user(self, username):
        attrs = [{"Name": "sub", "Value": username}]
        if username in self.emails:
            attrs.append({"Name": "email", "Value": self.emails[username]})
        return {"Username": username, "Attributes": attrs, "UserStatus": "CONFIRMED", "Enabled": True}

    def admin_get_user(self, UserPoolId, Username):
        if Username not in self.groups:
            from botocore.exceptions import ClientError

            raise ClientError({"Error": {"Code": "UserNotFoundException"}}, "AdminGetUser")
        return {"Username": Username}

    def list_users(self, UserPoolId, Filter, Limit):
        self.filters.append(Filter)
        if not Filter.startswith('email ^= "'):
            return {"Users": []}
        prefix = Filter.removeprefix('email ^= "').removesuffix('"')
        hits = [u for u, e in self.emails.items() if e.startswith(prefix)]
        return {"Users": [self._user(u) for u in hits[:Limit]]}

    def list_users_in_group(self, UserPoolId, GroupName, Limit):
        return {"Users": [self._user(u) for u, g in self.groups.items() if GroupName in g]}

    def admin_list_groups_for_user(self, UserPoolId, Username):
        return {"Groups": [{"GroupName": g} for g in sorted(self.groups[Username])]}

    def admin_add_user_to_group(self, UserPoolId, Username, GroupName):
        self.groups[Username].add(GroupName)

    def admin_remove_user_from_group(self, UserPoolId, Username, GroupName):
        self.groups[Username].discard(GroupName)

    def admin_user_global_sign_out(self, UserPoolId, Username):
        self.signed_out.append(Username)


@pytest.fixture(scope="module")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _token(key, sub: str, groups: list[str] | None = None) -> str:
    now = int(time.time())
    claims = {
        "sub": sub,
        "iss": ISSUER,
        "client_id": CLIENT_ID,
        "token_use": "access",
        "iat": now,
        "exp": now + 300,
    }
    if groups is not None:
        claims["cognito:groups"] = groups
    return jwt.encode(claims, key, algorithm="RS256")


@pytest.fixture
def setup(rsa_key, db_session, monkeypatch):
    monkeypatch.setattr("app.auth.admin_router.get_settings", lambda: _settings_with_pool())
    operator_sub = str(uuid.uuid4())
    target_sub = str(uuid.uuid4())
    db_session.add(User(id=target_sub))
    db_session.flush()

    idp = FakeIdp(
        {operator_sub: {"operator", "test"}, target_sub: {"test"}},
        {operator_sub: "op@example.com", target_sub: "target@example.com"},
    )
    verifier = TokenVerifier(ISSUER, CLIENT_ID, key_resolver=lambda _t: rsa_key.public_key())
    app.dependency_overrides[get_token_verifier] = lambda: verifier
    app.dependency_overrides[get_cognito_client] = lambda: idp
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        yield {
            "client": TestClient(app),
            "idp": idp,
            "operator": _token(rsa_key, operator_sub, ["operator", "test"]),
            "operator_sub": operator_sub,
            "user": _token(rsa_key, str(uuid.uuid4()), ["test"]),
            "target_sub": target_sub,
        }
    finally:
        app.dependency_overrides.clear()


def _settings_with_pool():
    from app.config import Settings, get_settings

    base = get_settings()
    return Settings(
        **{**base.model_dump(), "cognito_user_pool_id": base.cognito_user_pool_id or "pool-test"},
    )


def _put(ctx, sub: str, role: str, token: str):
    return ctx["client"].put(
        f"/admin/users/{sub}/role",
        json={"role": role},
        headers={"Authorization": f"Bearer {token}"},
    )


def test_operator_changes_role_to_mentor(setup):
    r = _put(setup, setup["target_sub"], "mentor", setup["operator"])
    assert r.status_code == 200, r.text
    assert r.json() == {"user_id": setup["target_sub"], "previous_role": "user", "role": "mentor"}
    assert setup["idp"].groups[setup["target_sub"]] == {"mentor", "test"}
    assert setup["idp"].signed_out == [setup["target_sub"]]


def test_change_back_to_user_removes_role_group(setup):
    setup["idp"].groups[setup["target_sub"]] = {"operator", "test"}
    r = _put(setup, setup["target_sub"], "user", setup["operator"])
    assert r.status_code == 200
    assert r.json()["previous_role"] == "operator"
    assert setup["idp"].groups[setup["target_sub"]] == {"test"}


def test_non_operator_forbidden(setup):
    assert _put(setup, setup["target_sub"], "mentor", setup["user"]).status_code == 403


def test_self_change_forbidden(setup):
    r = _put(setup, setup["operator_sub"], "user", setup["operator"])
    assert r.status_code == 403
    assert r.json()["code"] == "self_change_forbidden"


def test_system_role_rejected(setup):
    r = _put(setup, setup["target_sub"], "system", setup["operator"])
    assert r.status_code == 422
    assert r.json()["code"] == "validation_error"


def test_unknown_user_not_found(setup):
    r = _put(setup, str(uuid.uuid4()), "mentor", setup["operator"])
    assert r.status_code == 404
    assert r.json()["code"] == "not_found"


def test_cognito_user_without_users_row_gets_row(setup, db_session):
    """가입만 하고 아무것도 저장하지 않은 사용자(users 행 없음)도 역할을 바꿀 수 있다."""
    fresh = str(uuid.uuid4())
    setup["idp"].groups[fresh] = {"test"}
    r = _put(setup, fresh, "operator", setup["operator"])
    assert r.status_code == 200, r.text
    assert setup["idp"].groups[fresh] == {"operator", "test"}
    row = db_session.get(User, fresh)
    assert row is not None and row.token_not_before is not None


def test_deleted_user_not_found(setup, db_session):
    row = db_session.get(User, setup["target_sub"])
    row.deleted_at = datetime.now(UTC)
    db_session.flush()
    assert _put(setup, setup["target_sub"], "mentor", setup["operator"]).status_code == 404


def test_unauthenticated(setup):
    r = setup["client"].put(f"/admin/users/{setup['target_sub']}/role", json={"role": "mentor"})
    assert r.status_code == 401


def test_system_account_role_protected(setup, db_session):
    batch_sub = str(uuid.uuid4())
    db_session.add(User(id=batch_sub))
    db_session.flush()
    setup["idp"].groups[batch_sub] = {"system", "test"}
    r = _put(setup, batch_sub, "operator", setup["operator"])
    assert r.status_code == 403
    assert r.json()["code"] == "system_account_protected"
    assert setup["idp"].groups[batch_sub] == {"system", "test"}


def _list(ctx, token: str, **params):
    return ctx["client"].get("/admin/users", params=params, headers={"Authorization": f"Bearer {token}"})


def test_list_without_query_returns_role_holders(setup):
    setup["idp"].groups[setup["target_sub"]] = {"mentor", "test"}
    r = _list(setup, setup["operator"])
    assert r.status_code == 200, r.text
    got = {(u["email"], u["role"]) for u in r.json()}
    assert got == {("op@example.com", "operator"), ("target@example.com", "mentor")}


def test_search_by_email_prefix(setup):
    r = _list(setup, setup["operator"], email=" target")
    assert r.status_code == 200, r.text
    assert r.json() == [
        {
            "user_id": setup["target_sub"],
            "email": "target@example.com",
            "role": "user",
            "status": "CONFIRMED",
            "enabled": True,
        }
    ]
    assert setup["idp"].filters[-1] == 'email ^= "target"'


@pytest.mark.parametrize("bad", ['a" or sub ^= "', "a" + chr(92) + "b", "x" * 129])
def test_search_rejects_filter_injection(setup, bad):
    r = _list(setup, setup["operator"], email=bad)
    assert r.status_code == 422
    assert setup["idp"].filters == []


def test_list_requires_operator(setup):
    assert _list(setup, setup["user"]).status_code == 403
