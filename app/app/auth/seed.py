"""Cognito 시드 계정 적재 (D6). 로컬(cognito-local)과 staging(Helm seed Job, D5) 공용.

멱등이다. 그룹·계정이 이미 있으면 건너뛰고 비밀번호와 그룹 소속만 다시 맞춘다.
Helm post-install hook 으로 매 배포마다 돌아도 안전해야 한다.

입력(환경변수)
- COGNITO_USER_POOL_ID, AWS_REGION
- COGNITO_LOCAL_ENDPOINT: 있으면 cognito-local 로 보낸다(없으면 AWS)
- SEED_PASSWORD: 전 계정 공통 비밀번호. staging 은 Secrets Manager nesume/<env>/app 의 필드로 주입
- SEED_EMAIL_DOMAIN: 기본 example.com

계정(roles-grades.md 8장): test-user1·test-user2(user), test-mentor1(mentor), test-operator1(operator),
svc-batch(system). 전부 test 그룹.
svc-batch 는 Helm Secret 의 BATCH_USERNAME/BATCH_PASSWORD 와 같은 값이어야 한다.

운영자 TOTP 등록은 여기서 하지 않는다(D7 화면).
러너(B16·D13)는 associate/verify_software_token 으로 직접 등록한다.

실행
    로컬:    docker compose run --rm -e SEED_PASSWORD='...' test python -m app.auth.seed
    staging: helm values seed.enabled=true (deploy/nesume/templates/seed-job.yaml)
"""
import argparse
import logging
import os
import sys

import boto3
from botocore.exceptions import ClientError

log = logging.getLogger("nesume.seed")

# 그룹 이름 = Role 값(app/app/auth/cognito.py). test 는 역할이 아니라 플래그.
ROLE_GROUPS = ("mentor", "operator", "system")
TEST_GROUP = "test"
ALL_GROUPS = (*ROLE_GROUPS, TEST_GROUP)

# (로컬 파트, 역할 그룹 또는 None)
SEED_ACCOUNTS: tuple[tuple[str, str | None], ...] = (
    ("test-user1", None),
    ("test-user2", None),
    ("test-mentor1", "mentor"),
    ("test-operator1", "operator"),
    ("svc-batch", "system"),
)


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def make_client():
    """cognito-idp 클라이언트. COGNITO_LOCAL_ENDPOINT 가 있으면 cognito-local, 없으면 AWS."""
    return boto3.client(
        "cognito-idp",
        region_name=_env("AWS_REGION"),
        endpoint_url=os.environ.get("COGNITO_LOCAL_ENDPOINT") or None,
    )


def _code(e: ClientError) -> str:
    return e.response.get("Error", {}).get("Code", "")


def ensure_group(idp, pool_id: str, name: str) -> bool:
    """그룹 생성. 이미 있으면 False.

    AWS 는 중복 생성에 GroupExistsException 을 내지만 cognito-local 은 조용히 덮어쓴다. 먼저 조회한다.
    """
    try:
        idp.get_group(UserPoolId=pool_id, GroupName=name)
        return False
    except ClientError as e:
        if _code(e) != "ResourceNotFoundException":
            raise
    try:
        idp.create_group(UserPoolId=pool_id, GroupName=name)
        return True
    except ClientError as e:
        if _code(e) == "GroupExistsException":
            return False
        raise


def ensure_user(idp, pool_id: str, email: str, password: str) -> bool:
    """계정 생성(초대 메일 없음, email_verified). 이미 있으면 False.

    비밀번호는 항상 permanent 로 다시 설정한다.
    """
    created = True
    try:
        idp.admin_create_user(
            UserPoolId=pool_id,
            Username=email,
            UserAttributes=[
                {"Name": "email", "Value": email},
                {"Name": "email_verified", "Value": "true"},
            ],
            MessageAction="SUPPRESS",
        )
    except ClientError as e:
        if _code(e) != "UsernameExistsException":
            raise
        created = False
    idp.admin_set_user_password(UserPoolId=pool_id, Username=email, Password=password, Permanent=True)
    return created


def ensure_membership(idp, pool_id: str, email: str, groups: tuple[str, ...]) -> None:
    """지정 그룹에 추가. 지정되지 않은 역할 그룹에 들어 있으면 제거한다(역할 그룹은 하나만)."""
    current = {
        g["GroupName"]
        for g in idp.admin_list_groups_for_user(UserPoolId=pool_id, Username=email).get("Groups", [])
    }
    for g in groups:
        if g not in current:
            idp.admin_add_user_to_group(UserPoolId=pool_id, Username=email, GroupName=g)
    for g in current & set(ROLE_GROUPS):
        if g not in groups:
            idp.admin_remove_user_from_group(UserPoolId=pool_id, Username=email, GroupName=g)


def seed_accounts(idp, pool_id: str, password: str, domain: str) -> list[dict]:
    results = []
    for name in ALL_GROUPS:
        created = ensure_group(idp, pool_id, name)
        log.info("group %s: %s", name, "created" if created else "exists")

    for local_part, role in SEED_ACCOUNTS:
        email = f"{local_part}@{domain}"
        created = ensure_user(idp, pool_id, email, password)
        groups = (role, TEST_GROUP) if role else (TEST_GROUP,)
        ensure_membership(idp, pool_id, email, groups)
        log.info("user %s: %s groups=%s", email, "created" if created else "exists", ",".join(groups))
        results.append({"email": email, "role": role or "user", "groups": list(groups), "created": created})
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="nesume Cognito seed accounts (D6)")
    parser.add_argument(
        "--docs",
        action="store_true",
        help="시드 문서(자소서·경험·공유)도 적재한다. B API 확정 뒤 구현 예정.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s", stream=sys.stdout)

    pool_id = _env("COGNITO_USER_POOL_ID")
    password = _env("SEED_PASSWORD")
    domain = os.environ.get("SEED_EMAIL_DOMAIN") or "example.com"

    idp = make_client()
    results = seed_accounts(idp, pool_id, password, domain)
    log.info("done: %d accounts (%d created)", len(results), sum(r["created"] for r in results))

    if args.docs:
        # 시드 문서는 B API(자소서·경험·공유)로 적재한다. B API 확정 뒤 채운다.
        log.warning("--docs is not implemented yet (waiting for B document APIs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
