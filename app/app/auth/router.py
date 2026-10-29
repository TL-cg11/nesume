"""GET /auth/me (D7). web 이 로그인 직후와 새로고침 때 호출해 role·is_test 를 확인한다.

로그인·가입·비밀번호 재설정은 Cognito 가 처리하므로 백엔드 엔드포인트가 없다.

mfa_required: TOTP 를 아직 등록하지 않은 운영자면 true. web 은 이 값을 보고 /mfa/setup 으로 보내며,
등록 전에는 이 경로 외 모든 API 가 403 mfa_required 다(dependencies.operator_mfa_gate).
"""
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth.cognito import AuthenticatedUser, Role
from app.auth.dependencies import operator_mfa_pending
from app.config import Settings, get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


class MeResponse(BaseModel):
    user_id: str
    role: Role
    is_test: bool
    username: str | None = None
    mfa_required: bool = False


@router.get("/me", response_model=MeResponse)
def me(user: AuthenticatedUser, settings: Annotated[Settings, Depends(get_settings)]) -> MeResponse:
    return MeResponse(
        user_id=user.sub,
        role=user.role,
        is_test=user.is_test,
        username=user.username,
        mfa_required=operator_mfa_pending(user, settings, refresh=True),
    )
