"""운영자 TOTP 등록 여부 조회 (D7).

액세스 토큰에는 MFA 통과 여부(amr)가 없다. AdminGetUser 의 UserMFASettingList 에 SOFTWARE_TOKEN_MFA 가
있으면 등록된 것으로 본다. 결과는 sub 별로 5분 캐시한다(운영자 수가 적어 메모리 캐시로 충분).

IAM(D9): 앱 IRSA 에 cognito-idp:AdminGetUser.
cognito-local 이 MFA 목록을 주지 않으면 로컬은 OPERATOR_MFA_REQUIRED=false 로 끈다.
"""
import logging
import threading
import time

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.config import get_settings

log = logging.getLogger("nesume.auth.mfa")

CACHE_SECONDS = 300
TOTP_SETTING = "SOFTWARE_TOKEN_MFA"

_cache: dict[str, tuple[bool, float]] = {}
_lock = threading.Lock()


def _client():
    s = get_settings()
    return boto3.client(
        "cognito-idp",
        region_name=s.aws_region,
        endpoint_url=s.cognito_local_endpoint,
        config=Config(connect_timeout=2, read_timeout=5, retries={"max_attempts": 2}),
    )


def _lookup(sub: str) -> bool:
    s = get_settings()
    if not s.cognito_user_pool_id:
        return False
    try:
        user = _client().admin_get_user(UserPoolId=s.cognito_user_pool_id, Username=sub)
    except (ClientError, BotoCoreError) as e:
        # 조회 실패는 "미등록"으로 본다(fail closed). 운영자는 403 mfa_required 를 받는다.
        log.warning("admin_get_user failed", extra={"fields": {"error_type": type(e).__name__}})
        return False
    settings = user.get("UserMFASettingList") or []
    preferred = user.get("PreferredMfaSetting")
    return TOTP_SETTING in settings or preferred == TOTP_SETTING


def totp_enrolled(sub: str) -> bool:
    now = time.monotonic()
    with _lock:
        hit = _cache.get(sub)
        if hit and hit[1] > now:
            return hit[0]
    value = _lookup(sub)
    with _lock:
        _cache[sub] = (value, now + CACHE_SECONDS)
    return value


def invalidate(sub: str | None = None) -> None:
    """TOTP 등록 직후 등 캐시를 비울 때. sub 가 None 이면 전체."""
    with _lock:
        if sub is None:
            _cache.clear()
        else:
            _cache.pop(sub, None)
