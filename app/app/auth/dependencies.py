"""권한 의존성 (D7). 라우터 파라미터에 Depends(...) 한 줄로 건다.

    from app.auth import Role, require_interactive, require_operator_mfa, require_role

    @router.post("/rewrite")
    def rewrite(user: CurrentUser = Depends(require_interactive)): ...        # system 403 interactive_only
    @router.get("/shared")
    def shared(user: CurrentUser = Depends(require_role(Role.MENTOR))): ...  # mentor 만
    @router.put("/templates/{id}/activate")
    def activate(user: CurrentUser = Depends(require_operator_mfa)): ...     # operator + TOTP + 최근 로그인

403 은 D3 AppError 형식({"detail","code","request_id"}). 401 은 B 형식 그대로(get_current_user).
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
