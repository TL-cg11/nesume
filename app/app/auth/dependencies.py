"""권한 의존성 (D7). 라우터 파라미터에 Depends(...) 한 줄로 건다.

    from app.auth import Role, require_interactive, require_operator_mfa, require_role

    @router.post("/rewrite")
    def rewrite(user: CurrentUser = Depends(require_interactive)): ...        # system 403 interactive_only
    @router.get("/shared")
    def shared(user: CurrentUser = Depends(require_role(Role.MENTOR))): ...  # mentor 만
    @router.put("/templates/{id}/activate")
    def activate(user: CurrentUser = Depends(require_operator_mfa)): ...     # operator + TOTP + 최근 로그인

403 은 D3 AppError 형식({"detail","code","request_id"}). 401 은 B 형식 그대로(get_current_user).

operator_mfa_gate 는 라우트가 아니라 앱 전역(main.py FastAPI(dependencies=...))에 건다.
"""
import time
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth import mfa
from app.auth.cognito import (
    AuthenticatedUser,
    CurrentUser,
    Role,
    TokenInvalid,
    TokenVerifier,
    _is_revoked,
    get_token_verifier,
)
from app.config import Settings, get_settings
from app.core.errors import ForbiddenError

_optional_bearer = HTTPBearer(auto_error=False)


def require_role(*roles: Role) -> Callable[..., CurrentUser]:
    """지정 역할만 통과. 아니면 403 forbidden."""
    allowed = frozenset(roles)

    def _dep(user: AuthenticatedUser) -> CurrentUser:
        if user.role not in allowed:
            raise ForbiddenError("이 기능을 사용할 권한이 없습니다.")
        return user

    return _dep


def require_interactive(user: AuthenticatedUser) -> CurrentUser:
    """대화형 엔드포인트(리라이팅·면접 등). matrix.yaml 의 'system 대화형 불가'를 여기서 막는다."""
    if user.role is Role.SYSTEM:
        raise ForbiddenError("시스템 계정은 이 기능을 호출할 수 없습니다.", code="interactive_only")
    return user


def require_operator_mfa(
    user: AuthenticatedUser,
    settings: Annotated[Settings, Depends(get_settings)],
) -> CurrentUser:
    """운영자 보호 API. operator 역할 + TOTP 등록 + 최근 N분 내 로그인(auth_time).

    OPERATOR_MFA_REQUIRED=false(로컬) 면 역할만 확인한다.
    액세스 토큰에 amr 이 없어 MFA 통과 여부는 알 수 없다. 대신 TOTP 등록 여부(AdminGetUser)와
    로그인 시각으로 판단한다(D6 1장). auth_time 이 없는 토큰(일부 로컬 발급 경로)은 iat 로 대체한다.
    """
    if user.role is not Role.OPERATOR:
        raise ForbiddenError("운영자만 사용할 수 있습니다.")
    if not settings.operator_mfa_required:
        return user
    if not mfa.totp_enrolled(user.sub):
        raise ForbiddenError("TOTP 등록이 필요합니다.", code="mfa_required")
    logged_in_at = user.auth_time if user.auth_time is not None else user.iat
    if logged_in_at is None or time.time() - logged_in_at > settings.mfa_session_minutes * 60:
        raise ForbiddenError("다시 로그인해 주세요.", code="mfa_session_expired")
    return user


def operator_mfa_pending(user: CurrentUser, settings: Settings, *, refresh: bool = False) -> bool:
    """TOTP 를 아직 등록하지 않은 운영자인가. OPERATOR_MFA_REQUIRED=false(로컬) 면 항상 False."""
    if user.role is not Role.OPERATOR or not settings.operator_mfa_required:
        return False
    if refresh:
        mfa.invalidate(user.sub)  # /auth/me: 방금 등록했으면 캐시(5분)를 기다리지 않고 바로 풀린다
    return not mfa.totp_enrolled(user.sub)


# TOTP 미등록 운영자도 부를 수 있는 경로. 등록은 브라우저가 Cognito 에 직접 하므로 /auth/me 만 연다.
MFA_GATE_EXEMPT_PATHS = frozenset({"/auth/me"})


def operator_mfa_gate(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_optional_bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    """앱 전역 의존성(main.py). TOTP 미등록 운영자 토큰은 /auth/me 외 모든 API 에서 403 mfa_required.

    roles-grades.md: "MFA 미완료 운영자 토큰은 user 로 격하하지 않고 거부한다".
    토큰이 없거나 유효하지 않으면 그냥 통과시킨다 → 401/503 판단은 각 라우트의 get_current_user 몫.
    검증기는 Depends 로 받지 않는다: Cognito 설정이 없는 테스트 앱에서 공개 API 까지 500 이 나지 않게
    본문에서 꺼낸다(dependency_overrides 는 그대로 따른다).
    """
    if not settings.operator_mfa_required:
        return
    if credentials is None or credentials.scheme.lower() != "bearer":
        return
    if request.url.path in MFA_GATE_EXEMPT_PATHS:
        return
    try:
        factory = request.app.dependency_overrides.get(get_token_verifier, get_token_verifier)
        user = factory().verify(credentials.credentials)
    except Exception:  # noqa: BLE001  TokenInvalid·설정 누락·JWKS 장애
        return
    if operator_mfa_pending(user, settings):
        raise ForbiddenError("TOTP 등록이 필요합니다.", code="mfa_required")


def get_current_user_optional(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_optional_bearer)],
    verifier: Annotated[TokenVerifier, Depends(get_token_verifier)],
) -> CurrentUser | None:
    """토큰이 없으면 None, 있으면 검증한다(유효하지 않아도 None). 공개 + 로그인 선택 화면용."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        return None
    try:
        user = verifier.verify(credentials.credentials)
    except TokenInvalid:
        return None
    except Exception:  # noqa: BLE001  JWKS 장애 등. 선택 인증이므로 익명으로 처리
        return None
    if _is_revoked(user):
        return None
    request.state.user_id = user.sub
    request.state.role = user.role.value
    request.state.is_test = user.is_test
    return user
