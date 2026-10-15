"""Cognito Access Token 검증 및 FastAPI 인증 의존성.

소유: D팀(tasks.md D7). B팀이 B 기능 개발을 위해 선행 작성한 초안이며 D7 리뷰·확장 대상이다.
D7에서 확장할 항목: require_role(), 운영자 MFA 세션 확인, 시스템 토큰, role 변경 시 토큰 무효화.
`CurrentUser`, `get_current_user` 인터페이스는 유지한다.

검증 항목
- 서명: RS256만 허용(alg 혼동 공격 방지). 공개키는 COGNITO_JWKS_URL에서 조회·캐시.
- 클레임: iss == COGNITO_ISSUER, token_use == "access", client_id == COGNITO_CLIENT_ID,
  exp/iat/sub 필수.
- Access Token에는 aud가 없으므로 client_id로 발급 대상을 확인한다.

역할(spec 5.2, 6.1)
- `cognito:groups` 클레임에서 읽는다. custom 속성은 Access Token에 포함되지 않으므로 사용하지 않는다.
- 역할 그룹이 없으면 일반 사용자, 2개 이상이면 설정 오류로 보고 거부한다(fail closed).
- 역할은 매 요청 토큰에서만 읽는다(spec 7.4 멀티턴 방어).
"""
from dataclasses import dataclass
from enum import StrEnum
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


class Role(StrEnum):
    # 그룹 이름 = 값. 최종 명칭은 D1(역할 정의) 확정 시 맞춘다.
    USER = "user"
    MENTOR = "mentor"
    OPERATOR = "operator"
    SYSTEM = "system"


@dataclass(frozen=True)
class CurrentUser:
    sub: str
    role: Role = Role.USER
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
        return CurrentUser(sub=sub, role=_role_from_groups(claims), username=claims.get("username"))


def _role_from_groups(claims: dict) -> Role:
    groups = claims.get("cognito:groups") or []
    if not isinstance(groups, list):
        raise TokenInvalid()
    roles = {Role(g) for g in groups if g in Role._value2member_map_}
    if not roles:
        return Role.USER
    if len(roles) > 1:
        raise TokenInvalid()
    return roles.pop()


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
