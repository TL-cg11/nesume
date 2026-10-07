import hashlib
import hmac
import json
import os
import time
import uuid

import boto3
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import get_settings
from app.security.auth import (
    AuthenticatedUser,
    JwksKeyResolver,
    TokenVerifier,
    get_token_verifier,
)

ISSUER = "https://issuer.test/pool"
CLIENT_ID = "test-client"


def _make_app() -> FastAPI:
    app = FastAPI()

    @app.get("/whoami")
    def whoami(user: AuthenticatedUser) -> dict:
        return {"sub": user.sub}

    return app


# ---------------------------------------------------------------------------
# 단위 테스트: 테스트용 RSA 키로 서명한 토큰으로 검증 로직 확인
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def unit_client(rsa_key):
    app = _make_app()
    verifier = TokenVerifier(ISSUER, CLIENT_ID, key_resolver=lambda _t: rsa_key.public_key())
    app.dependency_overrides[get_token_verifier] = lambda: verifier
    return TestClient(app)


def _claims(**overrides):
    now = int(time.time())
    c = {
        "sub": str(uuid.uuid4()),
        "iss": ISSUER,
        "client_id": CLIENT_ID,
        "token_use": "access",
        "iat": now,
        "exp": now + 300,
    }
    c.update(overrides)
    return {k: v for k, v in c.items() if v is not None}


def _sign(key, claims, alg="RS256"):
    return jwt.encode(claims, key, algorithm=alg)


def _get(client, token=None, scheme="Bearer"):
    headers = {"Authorization": f"{scheme} {token}"} if token is not None else {}
    return client.get("/whoami", headers=headers)


def test_valid_token_returns_sub(unit_client, rsa_key):
    claims = _claims()
    r = _get(unit_client, _sign(rsa_key, claims))
    assert r.status_code == 200
    assert r.json() == {"sub": claims["sub"]}


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"exp": int(time.time()) - 120}, id="expired"),
        pytest.param({"iss": "https://evil.test/pool"}, id="wrong-issuer"),
        pytest.param({"client_id": "other-client"}, id="wrong-client"),
        pytest.param({"token_use": "id"}, id="id-token"),
        pytest.param({"sub": None}, id="missing-sub"),
        pytest.param({"exp": None}, id="missing-exp"),
        pytest.param({"sub": ""}, id="empty-sub"),
    ],
)
def test_invalid_claims_rejected(unit_client, rsa_key, overrides):
    r = _get(unit_client, _sign(rsa_key, _claims(**overrides)))
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


def test_signature_from_other_key_rejected(unit_client):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert _get(unit_client, _sign(other, _claims())).status_code == 401


def test_tampered_payload_rejected(unit_client, rsa_key):
    header, _payload, sig = _sign(rsa_key, _claims()).split(".")
    forged = jwt.utils.base64url_encode(b'{"sub":"attacker","iss":"x"}').decode()
    assert _get(unit_client, f"{header}.{forged}.{sig}").status_code == 401


def test_alg_none_rejected(unit_client):
    token = jwt.encode(_claims(), key=None, algorithm="none")
    assert _get(unit_client, token).status_code == 401


def test_hs256_with_public_key_rejected(unit_client, rsa_key):
    # alg 혼동 공격: 공개키를 HMAC 비밀키로 사용
    pem = rsa_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    # PyJWT는 PEM을 HMAC 키로 쓰는 것을 막으므로 직접 서명한다
    b64 = lambda b: jwt.utils.base64url_encode(b).decode()  # noqa: E731
    signing_input = f"{b64(json.dumps({'alg': 'HS256', 'typ': 'JWT'}).encode())}.{b64(json.dumps(_claims()).encode())}"
    sig = hmac.new(pem, signing_input.encode(), hashlib.sha256).digest()
    assert _get(unit_client, f"{signing_input}.{b64(sig)}").status_code == 401


@pytest.mark.parametrize(
    "token,scheme",
    [
        pytest.param(None, "Bearer", id="no-header"),
        pytest.param("not-a-jwt", "Bearer", id="garbage"),
        pytest.param("abc", "Basic", id="basic-scheme"),
    ],
)
def test_missing_or_malformed_header_rejected(unit_client, token, scheme):
    assert _get(unit_client, token, scheme).status_code == 401


def test_error_body_does_not_leak_reason(unit_client, rsa_key):
    r = _get(unit_client, _sign(rsa_key, _claims(exp=int(time.time()) - 120)))
    assert r.json() == {"detail": "Not authenticated"}


def test_jwks_unreachable_returns_503():
    app = _make_app()
    verifier = TokenVerifier(
        ISSUER, CLIENT_ID, key_resolver=JwksKeyResolver("http://127.0.0.1:1/jwks.json")
    )
    app.dependency_overrides[get_token_verifier] = lambda: verifier
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode(_claims(), other, algorithm="RS256", headers={"kid": "k1"})
    assert _get(TestClient(app), token).status_code == 503


# ---------------------------------------------------------------------------
# 통합 테스트: cognito-local이 실제로 발급한 토큰을 환경변수 설정 그대로 검증
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def cognito_user():
    s = get_settings()
    idp = boto3.client(
        "cognito-idp",
        region_name=s.aws_region,
        endpoint_url=os.environ["COGNITO_LOCAL_ENDPOINT"],
    )
    email = f"test-{uuid.uuid4().hex[:12]}@example.com"
    password = "Test!Passw0rd-" + uuid.uuid4().hex[:6]
    signup = idp.sign_up(
        ClientId=s.cognito_client_id,
        Username=email,
        Password=password,
        UserAttributes=[{"Name": "email", "Value": email}],
    )
    idp.admin_confirm_sign_up(UserPoolId=s.cognito_user_pool_id, Username=email)
    auth = idp.initiate_auth(
        ClientId=s.cognito_client_id,
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": email, "PASSWORD": password},
    )["AuthenticationResult"]
    yield {"sub": signup["UserSub"], "access": auth["AccessToken"], "id": auth["IdToken"]}
    idp.admin_delete_user(UserPoolId=s.cognito_user_pool_id, Username=email)


@pytest.fixture
def real_client():
    get_token_verifier.cache_clear()
    return TestClient(_make_app())


def test_cognito_local_access_token_accepted(real_client, cognito_user):
    r = _get(real_client, cognito_user["access"])
    assert r.status_code == 200
    assert r.json() == {"sub": cognito_user["sub"]}


def test_cognito_local_id_token_rejected(real_client, cognito_user):
    assert _get(real_client, cognito_user["id"]).status_code == 401
