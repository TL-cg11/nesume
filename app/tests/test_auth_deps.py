"""D7 인증 의존성 테스트. B test_auth.py 의 _claims/_sign/rsa_key 패턴을 복사해 쓴다(import 아님)."""
import time
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth import mfa
from app.auth.cognito import AuthenticatedUser, CurrentUser, Role, TokenVerifier, get_token_verifier
from app.auth.dependencies import (
    get_current_user_optional,
    operator_mfa_gate,
    require_interactive,
    require_operator_mfa,
    require_role,
)
from app.auth.router import router as auth_router
from app.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.request_id import RequestIdMiddleware

ISSUER = "https://issuer.test/pool"
CLIENT_WEB = "client-web"
CLIENT_RUNNER = "client-runner"


@pytest.fixture(scope="module")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _claims(**overrides):
    now = int(time.time())
    c = {
        "sub": str(uuid.uuid4()),
        "iss": ISSUER,
        "client_id": CLIENT_WEB,
        "token_use": "access",
        "iat": now,
        "auth_time": now,
        "exp": now + 300,
    }
    c.update(overrides)
    return {k: v for k, v in c.items() if v is not None}


def _sign(key, claims):
    return jwt.encode(claims, key, algorithm="RS256")


def _settings(**overrides) -> Settings:
    base = get_settings().model_dump()
    base.update(overrides)
    return Settings(**base)


def _make_app(settings: Settings) -> FastAPI:
    app = FastAPI(dependencies=[Depends(operator_mfa_gate)])  # main.py 와 같은 전역 가드
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)
    app.include_router(auth_router)

    @app.get("/whoami")
    def whoami(user: AuthenticatedUser) -> dict:
        return {"sub": user.sub, "role": user.role, "is_test": user.is_test}

    @app.get("/mentor-only")
    def mentor_only(user: CurrentUser = Depends(require_role(Role.MENTOR))) -> dict:
        return {"ok": True}

    @app.post("/rewrite")
    def rewrite(user: CurrentUser = Depends(require_interactive)) -> dict:
        return {"ok": True}

    @app.get("/admin-only")
    def admin_only(user: CurrentUser = Depends(require_operator_mfa)) -> dict:
        return {"ok": True}

    @app.get("/public")
    def public(user: CurrentUser | None = Depends(get_current_user_optional)) -> dict:
        return {"sub": user.sub if user else None}

    app.dependency_overrides[get_settings] = lambda: settings
    return app


@pytest.fixture
def make_client(rsa_key):
    def _make(**settings_overrides):
        settings = _settings(**settings_overrides)
        app = _make_app(settings)
        verifier = TokenVerifier(
            ISSUER, {CLIENT_WEB, CLIENT_RUNNER}, key_resolver=lambda _t: rsa_key.public_key()
        )
        app.dependency_overrides[get_token_verifier] = lambda: verifier
        return TestClient(app)

    return _make


def _get(client, path, token):
    return client.get(path, headers={"Authorization": f"Bearer {token}"})


# --- is_test / 복수 클라이언트 -------------------------------------------------


def test_test_group_sets_is_test(make_client, rsa_key):
    c = make_client()
    r = _get(c, "/whoami", _sign(rsa_key, _claims(**{"cognito:groups": ["mentor", "test"]})))
    assert r.status_code == 200
    assert r.json()["role"] == "mentor"
    assert r.json()["is_test"] is True


def test_without_test_group_is_not_test(make_client, rsa_key):
    r = _get(make_client(), "/whoami", _sign(rsa_key, _claims(**{"cognito:groups": ["operator"]})))
    assert r.json()["is_test"] is False


def test_second_client_id_accepted(make_client, rsa_key):
    assert _get(make_client(), "/whoami", _sign(rsa_key, _claims(client_id=CLIENT_RUNNER))).status_code == 200


def test_unknown_client_id_rejected(make_client, rsa_key):
    r = _get(make_client(), "/whoami", _sign(rsa_key, _claims(client_id="someone-else")))
    assert r.status_code == 401
    assert r.json() == {"detail": "Not authenticated"}


def test_verifier_accepts_single_client_id_string(rsa_key):
    # B 테스트 호환: TokenVerifier(ISSUER, "client", ...)
    v = TokenVerifier(ISSUER, CLIENT_WEB, key_resolver=lambda _t: rsa_key.public_key())
    user = v.verify(_sign(rsa_key, _claims(**{"cognito:groups": ["test"]})))
    assert user.is_test and user.auth_time is not None and user.iat is not None


# --- require_role / require_interactive -------------------------------------


def test_require_role_forbidden_uses_app_error_format(make_client, rsa_key):
    r = _get(make_client(), "/mentor-only", _sign(rsa_key, _claims()))
    assert r.status_code == 403
    body = r.json()
    assert body["code"] == "forbidden"
    assert body["request_id"] == r.headers["X-Request-ID"]


def test_require_role_allows_role(make_client, rsa_key):
    token = _sign(rsa_key, _claims(**{"cognito:groups": ["mentor"]}))
    assert _get(make_client(), "/mentor-only", token).status_code == 200


def test_system_token_rejected_on_interactive(make_client, rsa_key):
    c = make_client()
    token = _sign(rsa_key, _claims(**{"cognito:groups": ["system"]}))
    r = c.post("/rewrite", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403
    assert r.json()["code"] == "interactive_only"


def test_user_token_allowed_on_interactive(make_client, rsa_key):
    c = make_client()
    r = c.post("/rewrite", headers={"Authorization": f"Bearer {_sign(rsa_key, _claims())}"})
    assert r.status_code == 200


# --- require_operator_mfa ---------------------------------------------------


def _operator(**overrides):
    return _claims(**{"cognito:groups": ["operator", "test"]}, **overrides)


def test_operator_mfa_not_operator(make_client, rsa_key, monkeypatch):
    monkeypatch.setattr(mfa, "totp_enrolled", lambda _sub: True)
    r = _get(make_client(operator_mfa_required=True), "/admin-only", _sign(rsa_key, _claims()))
    assert r.status_code == 403
    assert r.json()["code"] == "forbidden"


def test_operator_mfa_required_when_not_enrolled(make_client, rsa_key, monkeypatch):
    monkeypatch.setattr(mfa, "totp_enrolled", lambda _sub: False)
    r = _get(make_client(operator_mfa_required=True), "/admin-only", _sign(rsa_key, _operator()))
    assert r.status_code == 403
    assert r.json()["code"] == "mfa_required"


def test_operator_mfa_session_expired(make_client, rsa_key, monkeypatch):
    monkeypatch.setattr(mfa, "totp_enrolled", lambda _sub: True)
    old = int(time.time()) - 60 * 60
    r = _get(
        make_client(operator_mfa_required=True, mfa_session_minutes=15),
        "/admin-only",
        _sign(rsa_key, _operator(auth_time=old, iat=old)),
    )
    assert r.status_code == 403
    assert r.json()["code"] == "mfa_session_expired"


def test_operator_mfa_passes_when_enrolled_and_recent(make_client, rsa_key, monkeypatch):
    monkeypatch.setattr(mfa, "totp_enrolled", lambda _sub: True)
    r = _get(make_client(operator_mfa_required=True), "/admin-only", _sign(rsa_key, _operator()))
    assert r.status_code == 200


def test_operator_mfa_falls_back_to_iat_without_auth_time(make_client, rsa_key, monkeypatch):
    monkeypatch.setattr(mfa, "totp_enrolled", lambda _sub: True)
    token = _sign(rsa_key, _operator(auth_time=None))
    r = _get(make_client(operator_mfa_required=True), "/admin-only", token)
    assert r.status_code == 200


def test_operator_mfa_disabled_locally(make_client, rsa_key, monkeypatch):
    monkeypatch.setattr(mfa, "totp_enrolled", lambda _sub: False)
    r = _get(make_client(operator_mfa_required=False), "/admin-only", _sign(rsa_key, _operator()))
    assert r.status_code == 200


# --- MFA_EXEMPT_TEST_OPERATORS (시드 test-operator1) ---------------------------------


def _exempt_client(make_client, **overrides):
    return make_client(
        operator_mfa_required=True, mfa_exempt_test_operators=True, app_env="dev", **overrides
    )


def test_test_operator_exempt_from_mfa(make_client, rsa_key, monkeypatch):
    monkeypatch.setattr(mfa, "totp_enrolled", lambda _sub: False)
    c = _exempt_client(make_client)
    old = int(time.time()) - 60 * 60  # 최근 로그인 요구도 면제
    token = _sign(rsa_key, _operator(auth_time=old, iat=old))
    assert _get(c, "/admin-only", token).status_code == 200
    assert _get(c, "/whoami", token).status_code == 200
    assert _get(c, "/auth/me", token).json()["mfa_required"] is False


def test_exemption_does_not_cover_real_operators(make_client, rsa_key, monkeypatch):
    """test 그룹이 아닌 운영자(콘솔에서 올린 실제 계정)는 면제되지 않는다."""
    monkeypatch.setattr(mfa, "totp_enrolled", lambda _sub: False)
    token = _sign(rsa_key, _claims(**{"cognito:groups": ["operator"]}))
    r = _get(_exempt_client(make_client), "/admin-only", token)
    assert r.status_code == 403
    assert r.json()["code"] == "mfa_required"


def test_exemption_ignored_in_production(make_client, rsa_key, monkeypatch):
    monkeypatch.setattr(mfa, "totp_enrolled", lambda _sub: False)
    c = make_client(operator_mfa_required=True, mfa_exempt_test_operators=True, app_env="production")
    r = _get(c, "/admin-only", _sign(rsa_key, _operator()))
    assert r.status_code == 403
    assert r.json()["code"] == "mfa_required"


def test_exemption_off_by_default(make_client, rsa_key, monkeypatch):
    monkeypatch.setattr(mfa, "totp_enrolled", lambda _sub: False)
    c = make_client(operator_mfa_required=True, mfa_exempt_test_operators=False, app_env="dev")
    assert _get(c, "/admin-only", _sign(rsa_key, _operator())).json()["code"] == "mfa_required"


def test_totp_enrolled_cache(monkeypatch):
    calls = []
    monkeypatch.setattr(mfa, "_lookup", lambda sub: calls.append(sub) or True)
    mfa.invalidate()
    assert mfa.totp_enrolled("s1") is True
    assert mfa.totp_enrolled("s1") is True
    assert calls == ["s1"]
    mfa.invalidate("s1")
    mfa.totp_enrolled("s1")
    assert calls == ["s1", "s1"]


# --- token_not_before (role 변경 뒤 무효화) ------------------------------------


def test_token_before_not_before_is_rejected(make_client, rsa_key, monkeypatch):
    now = datetime.now(UTC)
    monkeypatch.setattr("app.auth.cognito._token_not_before", lambda _sub: now)
    old = int((now - timedelta(minutes=5)).timestamp())
    assert _get(make_client(), "/whoami", _sign(rsa_key, _claims(iat=old, auth_time=old))).status_code == 401
    new = int((now + timedelta(seconds=5)).timestamp())
    assert _get(make_client(), "/whoami", _sign(rsa_key, _claims(iat=new, auth_time=new))).status_code == 200


def test_no_not_before_passes(make_client, rsa_key, monkeypatch):
    monkeypatch.setattr("app.auth.cognito._token_not_before", lambda _sub: None)
    assert _get(make_client(), "/whoami", _sign(rsa_key, _claims())).status_code == 200


# --- optional / me ----------------------------------------------------------


def test_optional_user_without_token(make_client):
    assert make_client().get("/public").json() == {"sub": None}


def test_optional_user_with_token(make_client, rsa_key):
    claims = _claims()
    assert _get(make_client(), "/public", _sign(rsa_key, claims)).json() == {"sub": claims["sub"]}


def test_me(make_client, rsa_key):
    claims = _claims(username="op@example.com", **{"cognito:groups": ["operator", "test"]})
    r = _get(make_client(operator_mfa_required=False), "/auth/me", _sign(rsa_key, claims))
    assert r.status_code == 200
    assert r.json() == {
        "user_id": claims["sub"],
        "role": "operator",
        "is_test": True,
        "username": "op@example.com",
        "mfa_required": False,
    }


# --- operator_mfa_gate (TOTP 미등록 운영자 전역 차단) + /auth/me mfa_required ------------


def test_gate_blocks_unenrolled_operator_everywhere(make_client, rsa_key, monkeypatch):
    monkeypatch.setattr(mfa, "totp_enrolled", lambda _sub: False)
    c = make_client(operator_mfa_required=True)
    token = _sign(rsa_key, _operator())
    for path in ("/whoami", "/public"):
        r = _get(c, path, token)
        assert r.status_code == 403, path
        assert r.json()["code"] == "mfa_required"
    assert c.post("/rewrite", headers={"Authorization": f"Bearer {token}"}).json()["code"] == "mfa_required"


def test_gate_leaves_me_open_and_reports_mfa_required(make_client, rsa_key, monkeypatch):
    monkeypatch.setattr(mfa, "totp_enrolled", lambda _sub: False)
    r = _get(make_client(operator_mfa_required=True), "/auth/me", _sign(rsa_key, _operator()))
    assert r.status_code == 200
    assert r.json()["mfa_required"] is True


def test_gate_passes_enrolled_operator(make_client, rsa_key, monkeypatch):
    monkeypatch.setattr(mfa, "totp_enrolled", lambda _sub: True)
    c = make_client(operator_mfa_required=True)
    token = _sign(rsa_key, _operator())
    assert _get(c, "/whoami", token).status_code == 200
    assert _get(c, "/auth/me", token).json()["mfa_required"] is False


def test_gate_ignores_non_operator_and_mfa_off(make_client, rsa_key, monkeypatch):
    monkeypatch.setattr(mfa, "totp_enrolled", lambda _sub: False)
    mentor = _sign(rsa_key, _claims(**{"cognito:groups": ["mentor"]}))
    assert _get(make_client(operator_mfa_required=True), "/whoami", mentor).status_code == 200
    assert _get(make_client(operator_mfa_required=True), "/auth/me", mentor).json()["mfa_required"] is False
    op = _sign(rsa_key, _operator())
    assert _get(make_client(operator_mfa_required=False), "/whoami", op).status_code == 200


def test_gate_leaves_invalid_token_to_route(make_client):
    r = _get(make_client(operator_mfa_required=True), "/whoami", "not-a-jwt")
    assert r.status_code == 401
    assert r.json() == {"detail": "Not authenticated"}


def test_me_refreshes_enrollment_cache(make_client, rsa_key, monkeypatch):
    """등록 직후 /auth/me 는 5분 캐시를 기다리지 않는다 → 이후 다른 API 도 바로 풀린다."""
    enrolled = {"value": False}
    monkeypatch.setattr(mfa, "_lookup", lambda _sub: enrolled["value"])
    mfa.invalidate()
    c = make_client(operator_mfa_required=True)
    token = _sign(rsa_key, _operator())
    assert _get(c, "/whoami", token).status_code == 403
    enrolled["value"] = True
    assert _get(c, "/auth/me", token).json()["mfa_required"] is False
    assert _get(c, "/whoami", token).status_code == 200
    mfa.invalidate()


def test_totp_not_enrolled_is_not_cached(monkeypatch):
    """미등록은 캐시하지 않는다 → 다른 파드에서 등록해도 이 파드가 바로 풀린다."""
    enrolled = {"value": False}
    monkeypatch.setattr(mfa, "_lookup", lambda _sub: enrolled["value"])
    mfa.invalidate()
    assert mfa.totp_enrolled("s2") is False
    enrolled["value"] = True
    assert mfa.totp_enrolled("s2") is True
    mfa.invalidate()


def test_me_unauthenticated(make_client):
    r = make_client().get("/auth/me")
    assert r.status_code == 401
    assert r.json() == {"detail": "Not authenticated"}
