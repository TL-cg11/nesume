"""D6 운영자 역할 변경 API 단위 테스트. Cognito 는 가짜 클라이언트로 대체한다."""
import time
import uuid

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

    def __init__(self, groups: dict[str, set[str]]):
        self.groups = groups  # username -> group set
        self.signed_out: list[str] = []

    def admin_get_user(self, UserPoolId, Username):
        if Username not in self.groups:
            from botocore.exceptions import ClientError

            raise ClientError({"Error": {"Code": "UserNotFoundException"}}, "AdminGetUser")
        return {"Username": Username}

    def list_users(self, UserPoolId, Filter, Limit):
        return {"Users": []}

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

    idp = FakeIdp({operator_sub: {"operator", "test"}, target_sub: {"test"}})
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


def test_unauthenticated(setup):
    r = setup["client"].put(f"/admin/users/{setup['target_sub']}/role", json={"role": "mentor"})
    assert r.status_code == 401
