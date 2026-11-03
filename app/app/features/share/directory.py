"""사용자 찾기(10/29): 이메일 → 멘토 계정, 사용자 ID → 이메일.

- 멘토 공유는 상대의 내부 ID를 알 수 없어 이메일로 지정한다(B10 후속). 멘토 그룹이 아니면 공유 불가
- AI 사용 기록(B11 화면)에서 질문한 사람을 이메일로 보여준다(운영자 전용)
Cognito 클라이언트는 D6의 `get_cognito_client`(로컬 cognito-local / AWS)를 그대로 쓴다.
IAM: cognito-idp:ListUsers, AdminListGroupsForUser(D6 IRSA에 이미 포함)
"""
from __future__ import annotations

import re

from app.config import get_settings

MENTOR_GROUP = "mentor"
_EMAIL = re.compile(r"^[^@\s\"]+@[^@\s\"]+\.[^@\s\"]+$")


class DirectoryUnavailable(RuntimeError):
    """Cognito 설정이 없다(로컬 설정 누락 등)."""


def _pool() -> str:
    pool = get_settings().cognito_user_pool_id
    if not pool:
        raise DirectoryUnavailable()
    return pool


def _attr(user: dict, name: str) -> str | None:
    return next((a["Value"] for a in user.get("Attributes", []) if a["Name"] == name), None)


def find_mentor_sub(idp, email: str) -> str | None:
    """이메일로 멘토 계정의 사용자 ID(sub)를 찾는다.

    없거나 멘토가 아니면 None — 어느 쪽인지 구분해 알리지 않는다(계정 존재 노출 방지).
    """
    email = (email or "").strip().lower()
    if not _EMAIL.match(email):
        return None
    pool = _pool()
    found = idp.list_users(UserPoolId=pool, Filter=f'email = "{email}"', Limit=1).get("Users", [])
    if not found:
        return None
    user = found[0]
    groups = idp.admin_list_groups_for_user(UserPoolId=pool, Username=user["Username"]).get("Groups", [])
    if MENTOR_GROUP not in {g["GroupName"] for g in groups}:
        return None
    return _attr(user, "sub")


def find_sub(idp, email: str) -> str | None:
    """이메일 → 사용자 ID(역할 무관). AI 사용 기록에서 사용자로 거를 때(운영자 전용)."""
    email = (email or "").strip().lower()
    if not _EMAIL.match(email):
        return None
    found = idp.list_users(UserPoolId=_pool(), Filter=f'email = "{email}"', Limit=1).get("Users", [])
    return _attr(found[0], "sub") if found else None


def emails_for(idp, subs: list[str]) -> dict[str, str]:
    """사용자 ID → 이메일. 찾지 못한 ID(삭제된 계정·익명화된 감사 로그)는 빠진다."""
    pool = _pool()
    out: dict[str, str] = {}
    for sub in dict.fromkeys(s for s in subs if s):
        if not re.fullmatch(r"[A-Za-z0-9-]{1,128}", sub):  # 필터 문자열에 넣으므로 형식 확인
            continue
        found = idp.list_users(UserPoolId=pool, Filter=f'sub = "{sub}"', Limit=1).get("Users", [])
        email = _attr(found[0], "email") if found else None
        if email:
            out[sub] = email
    return out
