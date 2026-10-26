"""Cognito Access Token 검증 및 FastAPI 인증 의존성.

소유: D팀(tasks.md D7). B팀이 B 기능 개발을 위해 선행 작성한 초안이며 D7 리뷰·확장 대상이다.
D7 확장(추가만, B 인터페이스 유지):
- `CurrentUser.is_test`(그룹 test), `auth_time`, `iat`, `groups`
- 앱 클라이언트 복수 허용(`COGNITO_CLIENT_IDS`, web·runner)
- role 변경 즉시 무효화: `users.token_not_before` ≥ `iat` 이면 401 (컬럼은 B 추가 예정. 없으면 건너뜀)
- 검증 결과를 `request.state`(user_id, role, is_test)에 기록 → 접근 로그(D3 미들웨어)
- 권한 의존성은 app/app/auth/dependencies.py, /auth/me 는 router.py

검증 항목
- 서명: RS256만 허용(alg 혼동 공격 방지). 공개키는 COGNITO_JWKS_URL에서 조회·캐시.
- 클레임: iss == COGNITO_ISSUER, token_use == "access", client_id ∈ COGNITO_CLIENT_IDS,
  exp/iat/sub 필수.
- Access Token에는 aud가 없으므로 client_id로 발급 대상을 확인한다.

역할(spec 5.2, 6.1)
- `cognito:groups` 클레임에서 읽는다. custom 속성은 Access Token에 포함되지 않으므로 사용하지 않는다.
- 역할 그룹이 없으면 일반 사용자, 2개 이상이면 설정 오류로 보고 거부한다(fail closed).
- 역할은 매 요청 토큰에서만 읽는다(spec 7.4 멀티턴 방어).
"""
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Any, Protocol

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.config import get_settings

ALLOWED_ALGORITHMS = ["RS256"]
LEEWAY_SECONDS = 30
TEST_GROUP = "test"  # 역할이 아닌 테스트 플래그 그룹(roles-grades.md 8장)
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
    # D7 추가. 기본값이 있어 B 호출(CurrentUser(sub=..., role=...))과 호환된다.
    is_test: bool = False
    auth_time: int | None = None  # 로그인 시각. 운영자 MFA 세션 판단(auth_time 없으면 iat)
    iat: int | None = None
    groups: tuple[str, ...] = ()


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
    def __init__(self, issuer: str, client_ids: str | Iterable[str], key_resolver: SigningKeyResolver):
        self._issuer = issuer
        # B 테스트의 TokenVerifier(ISSUER, CLIENT_ID, ...) 호출(str)과 D7 복수(set) 둘 다 받는다.
        self._client_ids = frozenset([client_ids] if isinstance(client_ids, str) else client_ids)
        if not self._client_ids:
            raise ValueError("client_ids must not be empty")
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
        if claims.get("client_id") not in self._client_ids:
            raise TokenInvalid()
        sub = claims["sub"]
        if not isinstance(sub, str) or not sub:
            raise TokenInvalid()
        groups = _groups(claims)
        return CurrentUser(
            sub=sub,
            role=_role_from_groups(claims),
            username=claims.get("username"),
            is_test=TEST_GROUP in groups,
            auth_time=_int_or_none(claims.get("auth_time")),
            iat=_int_or_none(claims.get("iat")),
            groups=groups,
        )


def _groups(claims: dict) -> tuple[str, ...]:
    groups = claims.get("cognito:groups") or []
    if not isinstance(groups, list):
        raise TokenInvalid()
    return tuple(g for g in groups if isinstance(g, str))


def _int_or_none(value: Any) -> int | None:
    return int(value) if isinstance(value, int | float) else None


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
    client_ids = s.cognito_client_id_set
    if not (s.cognito_issuer and client_ids and s.cognito_jwks_url):
        raise RuntimeError(
            "Cognito 설정이 없습니다: COGNITO_ISSUER, COGNITO_JWKS_URL, "
            "COGNITO_CLIENT_IDS(또는 COGNITO_CLIENT_ID)"
        )
    return TokenVerifier(
        issuer=s.cognito_issuer,
        client_ids=client_ids,
        key_resolver=JwksKeyResolver(s.cognito_jwks_url),
    )


def _token_not_before(sub: str) -> datetime | None:
    """users.token_not_before 조회. 컬럼이 아직 없으면(B 추가 전) None.

    get_current_user 에 get_db 의존성을 붙이지 않는 이유: B 단위 테스트(_make_app)가 DB 없이 돈다.
    컬럼이 생기면 PK 1건 조회라 비용이 작다. 행이 없으면(첫 요청) 통과한다.
    """
    from app.models import User

    column = getattr(User, "token_not_before", None)
    if column is None:
        return None
    from app.db import SessionLocal

    with SessionLocal() as session:
        return session.execute(select(column).where(User.id == sub)).scalar_one_or_none()


def _is_revoked(user: CurrentUser) -> bool:
    not_before = _token_not_before(user.sub)
    if not_before is None or user.iat is None:
        return False
    if not_before.tzinfo is None:
        not_before = not_before.replace(tzinfo=UTC)
    return datetime.fromtimestamp(user.iat, tz=UTC) < not_before


_bearer = HTTPBearer(auto_error=False)

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    verifier: Annotated[TokenVerifier, Depends(get_token_verifier)],
) -> CurrentUser:
    # 실패 사유는 응답에 노출하지 않는다(토큰 탐색 공격 방지). 토큰 값은 로그에 남기지 않는다.
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _UNAUTHORIZED
    try:
        user = verifier.verify(credentials.credentials)
    except TokenInvalid:
        raise _UNAUTHORIZED from None
    except KeySourceUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable",
        ) from None

    # role 변경(D6) 뒤 발급 전 토큰 거부. 응답은 B 형식(401 Not authenticated) 유지.
    if _is_revoked(user):
        raise _UNAUTHORIZED

    # 동기 의존성이라 ContextVar 가 미들웨어로 돌아오지 않는다.
    # scope["state"] 에 넣어 접근 로그(request_id.py)가 읽는다.
    request.state.user_id = user.sub
    request.state.role = user.role.value
    request.state.is_test = user.is_test
    return user


AuthenticatedUser = Annotated[CurrentUser, Depends(get_current_user)]
