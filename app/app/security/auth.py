"""Cognito Access Token 검증 및 FastAPI 인증 의존성.

임시 구현: 파트 4(인프라·인증)의 공통 인증 모듈로 대체될 예정이다.
대체 시에도 `CurrentUser`, `get_current_user` 인터페이스는 유지한다.

검증 항목
- 서명: RS256만 허용(alg 혼동 공격 방지). 공개키는 COGNITO_JWKS_URL에서 조회·캐시.
- 클레임: iss == COGNITO_ISSUER, token_use == "access", client_id == COGNITO_CLIENT_ID,
  exp/iat/sub 필수.
- Access Token에는 aud가 없으므로 client_id로 발급 대상을 확인한다.
"""
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any, Protocol

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings

ALLOWED_ALGORITHMS = ["RS256"]
LEEWAY_SECONDS = 30
JWKS_TIMEOUT_SECONDS = 3
JWKS_CACHE_SECONDS = 300


@dataclass(frozen=True)
class CurrentUser:
    sub: str
    username: str | None = None


class TokenInvalid(Exception):
    """토큰 자체가 유효하지 않음 → 401"""


class KeySourceUnavailable(Exception):
    """공개키 조회 실패(인증 서버 장애) → 503"""


class SigningKeyResolver(Protocol):
    def __call__(self, token: str) -> Any: ...


class JwksKeyResolver:
    def __init__(self, jwks_url: str):
        self._client = jwt.PyJWKClient(
            jwks_url,
            cache_keys=True,
            lifespan=JWKS_CACHE_SECONDS,
            timeout=JWKS_TIMEOUT_SECONDS,
        )

    def __call__(self, token: str) -> Any:
        try:
            return self._client.get_signing_key_from_jwt(token).key
        except jwt.PyJWKClientConnectionError as e:
            raise KeySourceUnavailable() from e
        except jwt.PyJWKClientError as e:
            # kid 불일치 등 → 토큰 문제
            raise TokenInvalid() from e
        except jwt.DecodeError as e:
            raise TokenInvalid() from e


class TokenVerifier:
    def __init__(self, issuer: str, client_id: str, key_resolver: SigningKeyResolver):
        self._issuer = issuer
        self._client_id = client_id
        self._resolve_key = key_resolver

    def verify(self, token: str) -> CurrentUser:
        key = self._resolve_key(token)
        try:
            claims = jwt.decode(
                token,
                key=key,
                algorithms=ALLOWED_ALGORITHMS,
                issuer=self._issuer,
                leeway=LEEWAY_SECONDS,
                options={"require": ["exp", "iat", "iss", "sub"], "verify_aud": False},
            )
        except jwt.InvalidTokenError as e:
            raise TokenInvalid() from e

        if claims.get("token_use") != "access":
            raise TokenInvalid()
        if claims.get("client_id") != self._client_id:
            raise TokenInvalid()
        sub = claims["sub"]
        if not isinstance(sub, str) or not sub:
            raise TokenInvalid()
        return CurrentUser(sub=sub, username=claims.get("username"))


@lru_cache
def get_token_verifier() -> TokenVerifier:
    s = get_settings()
    if not (s.cognito_issuer and s.cognito_client_id and s.cognito_jwks_url):
        raise RuntimeError("Cognito 설정(COGNITO_ISSUER, COGNITO_CLIENT_ID, COGNITO_JWKS_URL)이 없습니다.")
    return TokenVerifier(
        issuer=s.cognito_issuer,
        client_id=s.cognito_client_id,
        key_resolver=JwksKeyResolver(s.cognito_jwks_url),
    )


_bearer = HTTPBearer(auto_error=False)

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    verifier: Annotated[TokenVerifier, Depends(get_token_verifier)],
) -> CurrentUser:
    # 실패 사유는 응답에 노출하지 않는다(토큰 탐색 공격 방지). 토큰 값은 로그에 남기지 않는다.
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _UNAUTHORIZED
    try:
        return verifier.verify(credentials.credentials)
    except TokenInvalid:
        raise _UNAUTHORIZED from None
    except KeySourceUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable",
        ) from None


AuthenticatedUser = Annotated[CurrentUser, Depends(get_current_user)]
