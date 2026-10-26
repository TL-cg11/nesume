"""운영자용 역할 변경 API (D6).

PUT /admin/users/{user_id}/role  body {"role": "user" | "mentor" | "operator"}

역할은 Cognito 그룹이다(roles-grades.md 8장). 처리 순서:
  1. 금지 조건: 자기 자신(403 self_change_forbidden), system 부여(422), users 행 없음(404)
  2. 현재 역할 그룹 조회 → 제거 → 새 역할이 user 가 아니면 추가
  3. AdminUserGlobalSignOut(리프레시 무효화). cognito-local 은 미지원이라 실패해도 계속 진행
  4. users.token_not_before = now()  (이미 발급된 액세스 토큰 무효화. D7 이 iat 와 비교해 401)
     → B 가 컬럼을 추가하기 전까지는 건너뛴다(TODO).
  5. 로그 role_changed. 감사 로그 테이블 기록은 B11 API 확정 뒤 교체.

운영자 판정은 D7 require_operator_mfa(operator + TOTP 등록 + 최근 로그인).
IAM(D9 메모): 앱 IRSA 에 cognito-idp:AdminListGroupsForUser, AdminAddUserToGroup,
AdminRemoveUserFromGroup, AdminUserGlobalSignOut, AdminGetUser, ListUsers.
"""
import logging
from datetime import UTC, datetime
from typing import Annotated, Literal

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.cognito import CurrentUser, Role
from app.auth.dependencies import require_operator_mfa
from app.config import get_settings
from app.core.errors import AppError, ForbiddenError, NotFoundError
from app.db import get_db
from app.models import User

log = logging.getLogger("nesume.admin")

router = APIRouter(prefix="/admin", tags=["admin"])

ROLE_GROUPS = frozenset({Role.MENTOR.value, Role.OPERATOR.value, Role.SYSTEM.value})
AssignableRole = Literal["user", "mentor", "operator"]


class RoleChangeIn(BaseModel):
    role: AssignableRole


class RoleChangeOut(BaseModel):
    user_id: str
    previous_role: str
    role: str


def get_cognito_client():
    """cognito-idp 클라이언트. 로컬은 COGNITO_LOCAL_ENDPOINT(cognito-local), AWS 는 기본 엔드포인트."""
    s = get_settings()
    return boto3.client(
        "cognito-idp",
        region_name=s.aws_region,
        endpoint_url=s.cognito_local_endpoint,
        config=Config(connect_timeout=2, read_timeout=5, retries={"max_attempts": 2}),
    )


def _code(e: ClientError) -> str:
    return e.response.get("Error", {}).get("Code", "")


def _resolve_username(idp, pool_id: str, sub: str) -> str:
    """Cognito 내부 username 을 찾는다.

    AWS(username_attributes=email)는 username == sub 라 그대로 쓰면 되고,
    cognito-local 은 가입 시 준 값(email)이 username 이라 sub 로 ListUsers 필터를 건다.
    """
    try:
        idp.admin_get_user(UserPoolId=pool_id, Username=sub)
        return sub
    except ClientError as e:
        if _code(e) != "UserNotFoundException":
            raise
    found = idp.list_users(UserPoolId=pool_id, Filter=f'sub = "{sub}"', Limit=1).get("Users", [])
    if not found:
        raise NotFoundError("사용자를 찾을 수 없습니다.")
    return found[0]["Username"]


@router.put("/users/{user_id}/role", response_model=RoleChangeOut)
def change_user_role(
    user_id: str,
    body: RoleChangeIn,
    actor: Annotated[CurrentUser, Depends(require_operator_mfa)],
    db: Annotated[Session, Depends(get_db)],
    idp: Annotated[object, Depends(get_cognito_client)],
) -> RoleChangeOut:
    if user_id == actor.sub:
        raise ForbiddenError("자기 자신의 역할은 변경할 수 없습니다.", code="self_change_forbidden")

    # user_id 는 Cognito sub. 한 번도 로그인하지 않은 사용자는 users 행이 없어 404.
    user = db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise NotFoundError("사용자를 찾을 수 없습니다.")

    s = get_settings()
    if not s.cognito_user_pool_id:
        raise AppError("Cognito 설정이 없습니다.", code="cognito_not_configured", status_code=503)
    pool_id = s.cognito_user_pool_id

    username = _resolve_username(idp, pool_id, user_id)
    groups = idp.admin_list_groups_for_user(UserPoolId=pool_id, Username=username).get("Groups", [])
    current_roles = {g["GroupName"] for g in groups} & ROLE_GROUPS
    if not current_roles:
        previous_role = "user"
    elif len(current_roles) == 1:
        previous_role = next(iter(current_roles))
    else:
        previous_role = "invalid"  # 역할 그룹 2개 이상(설정 오류). 아래에서 모두 정리된다

    for g in current_roles:
        if g != body.role:
            idp.admin_remove_user_from_group(UserPoolId=pool_id, Username=username, GroupName=g)
    if body.role != "user" and body.role not in current_roles:
        idp.admin_add_user_to_group(UserPoolId=pool_id, Username=username, GroupName=body.role)

    # 리프레시 토큰 무효화. cognito-local 은 미지원(NotImplemented) → 건너뛴다.
    try:
        idp.admin_user_global_sign_out(UserPoolId=pool_id, Username=username)
    except ClientError as e:
        log.warning("admin_user_global_sign_out skipped", extra={"fields": {"error_code": _code(e)}})

    # 이미 발급된 액세스 토큰 무효화. B 가 users.token_not_before 컬럼을 추가하면 동작한다(D7 이 iat 와 비교).
    if hasattr(user, "token_not_before"):
        user.token_not_before = datetime.now(UTC)

    log.info(
        "role_changed",
        extra={"fields": {"user_id": user_id, "from": previous_role, "to": body.role, "actor": actor.sub}},
    )
    return RoleChangeOut(user_id=user_id, previous_role=previous_role, role=body.role)
