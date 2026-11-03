"""운영자용 역할 관리 API (D6). 화면은 web/src/features/admin/AdminUsersPage.jsx.

GET /admin/users?email=<앞부분>   이메일 앞부분 검색(최대 20명). 비우면 멘토·운영자 목록
PUT /admin/users/{user_id}/role  body {"role": "user" | "mentor" | "operator"}

역할은 Cognito 그룹이다(roles-grades.md 8장). 처리 순서:
  1. 금지 조건: 자기 자신(403 self_change_forbidden), system 부여(422), Cognito 에 없음·삭제 예약(404),
     system 계정 변경(403 system_account_protected. 배치 서비스 계정은 콘솔에서 바꾸지 않는다)
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
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.cognito import CurrentUser, Role
from app.auth.dependencies import require_operator_mfa
from app.config import get_settings
from app.core.errors import AppError, ForbiddenError, NotFoundError
from app.db import get_db
from app.models import User

log = logging.getLogger("nesume.admin")
# 역할 변경은 감사 성격 → log_type=audit 로 CloudWatch 감사 로그 그룹에 들어간다(D14)
audit_log = logging.getLogger("nesume.audit.admin")

router = APIRouter(prefix="/admin", tags=["admin"])

ROLE_GROUPS = frozenset({Role.MENTOR.value, Role.OPERATOR.value, Role.SYSTEM.value})
AssignableRole = Literal["user", "mentor", "operator"]


class RoleChangeIn(BaseModel):
    role: AssignableRole


class RoleChangeOut(BaseModel):
    user_id: str
    previous_role: str
    role: str


class AdminUserOut(BaseModel):
    user_id: str  # Cognito sub. PUT /admin/users/{user_id}/role 에 그대로 쓴다
    email: str | None
    role: str  # user | mentor | operator | system | invalid
    status: str | None  # Cognito UserStatus(CONFIRMED, UNCONFIRMED ...)
    enabled: bool


SEARCH_LIMIT = 20
LIST_ROLES = ("operator", "mentor")
# ListUsers Filter 에 그대로 넣으므로 따옴표·역슬래시·제어문자는 받지 않는다(필터 주입 방지)
EMAIL_QUERY_PATTERN = r'^[^"\\\x00-\x1f]{1,128}$'


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


def _attr(user: dict, name: str) -> str | None:
    for a in user.get("Attributes") or []:
        if a.get("Name") == name:
            return a.get("Value")
    return None


def _role_of(groups: set[str]) -> str:
    roles = groups & ROLE_GROUPS
    if not roles:
        return "user"
    return next(iter(roles)) if len(roles) == 1 else "invalid"


def _to_out(user: dict, role: str) -> AdminUserOut:
    return AdminUserOut(
        user_id=_attr(user, "sub") or user["Username"],
        email=_attr(user, "email"),
        role=role,
        status=user.get("UserStatus"),
        enabled=bool(user.get("Enabled", True)),
    )


@router.get("/users", response_model=list[AdminUserOut])
def list_users(
    actor: Annotated[CurrentUser, Depends(require_operator_mfa)],
    idp: Annotated[object, Depends(get_cognito_client)],
    email: Annotated[str | None, Query(pattern=EMAIL_QUERY_PATTERN)] = None,
) -> list[AdminUserOut]:
    """email 이 있으면 앞부분 일치 검색, 없으면 역할이 있는 사용자(운영자·멘토)."""
    s = get_settings()
    if not s.cognito_user_pool_id:
        raise AppError("Cognito 설정이 없습니다.", code="cognito_not_configured", status_code=503)
    pool_id = s.cognito_user_pool_id
    query = (email or "").strip()

    if not query:
        out: list[AdminUserOut] = []
        for role in LIST_ROLES:
            members = idp.list_users_in_group(UserPoolId=pool_id, GroupName=role, Limit=60).get("Users", [])
            out.extend(_to_out(u, role) for u in members)
        return out

    found = idp.list_users(
        UserPoolId=pool_id, Filter=f'email ^= "{query}"', Limit=SEARCH_LIMIT
    ).get("Users", [])
    out = []
    for u in found:
        groups = idp.admin_list_groups_for_user(UserPoolId=pool_id, Username=u["Username"]).get("Groups", [])
        out.append(_to_out(u, _role_of({g["GroupName"] for g in groups})))
    return out


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

    # user_id 는 Cognito sub. 삭제 예약된 사용자는 404.
    user = db.get(User, user_id)
    if user is not None and user.deleted_at is not None:
        raise NotFoundError("사용자를 찾을 수 없습니다.")

    s = get_settings()
    if not s.cognito_user_pool_id:
        raise AppError("Cognito 설정이 없습니다.", code="cognito_not_configured", status_code=503)
    pool_id = s.cognito_user_pool_id

    # Cognito 에 없으면 404. users 행은 첫 쓰기(자소서·경험 저장) 때 생기므로,
    # 가입만 한 사용자는 여기서 만든다(token_not_before 를 기록할 곳이 필요하다).
    username = _resolve_username(idp, pool_id, user_id)
    if user is None:
        user = User(id=user_id)
        db.add(user)
    groups = idp.admin_list_groups_for_user(UserPoolId=pool_id, Username=username).get("Groups", [])
    current_roles = {g["GroupName"] for g in groups} & ROLE_GROUPS
    # 역할 그룹 2개 이상이면 "invalid"(설정 오류). 아래에서 모두 정리된다
    previous_role = _role_of(current_roles)
    if Role.SYSTEM.value in current_roles:
        # 배치 서비스 계정(svc-batch). 역할을 바꾸면 배치가 멈추거나 사람 계정으로 쓰이게 된다
        raise ForbiddenError("시스템 계정의 역할은 바꿀 수 없습니다.", code="system_account_protected")

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

    audit_log.info(
        "role_changed",
        extra={"fields": {"user_id": user_id, "from": previous_role, "to": body.role, "actor": actor.sub}},
    )
    return RoleChangeOut(user_id=user_id, previous_role=previous_role, role=body.role)
