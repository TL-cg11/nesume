"""GET /auth/me (D7). web 이 로그인 직후와 새로고침 때 호출해 role·is_test 를 확인한다.

로그인·가입·비밀번호 재설정은 Cognito 가 처리하므로 백엔드 엔드포인트가 없다.
"""
from fastapi import APIRouter
from pydantic import BaseModel

from app.auth.cognito import AuthenticatedUser, Role

router = APIRouter(prefix="/auth", tags=["auth"])


class MeResponse(BaseModel):
    user_id: str
    role: Role
    is_test: bool
    username: str | None = None


@router.get("/me", response_model=MeResponse)
def me(user: AuthenticatedUser) -> MeResponse:
    return MeResponse(user_id=user.sub, role=user.role, is_test=user.is_test, username=user.username)
