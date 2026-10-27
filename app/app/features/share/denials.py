"""멘토의 권한 없는 열람 시도 감시 (10/26 회의, part2_guide 4.45·4.57).

멘토가 만료·취소됐거나 공유받지 않은 자소서(공유)를 **10분 안에 5회 이상** 열려고 하면 감사 로그에 1행 남긴다.
- 대상: 멘토 열람 API(`/mentor/shares/{id}`, 코멘트 작성·수정·삭제)에서 404가 나는 경우
- 같은 10분 구간에서는 5회째에 **한 번만** 기록한다(이후 시도는 다음 구간에서 다시 셈)
- 횟수는 C7 카운터 테이블(rate_limit_counters, 키 `share-deny:<멘토 ID>`)로 센다. 앱 서버가 여럿이라 메모리로 못 센다
- 거부 응답(404)은 요청 세션을 되돌리므로, 횟수·감사 로그는 **별도 세션**으로 바로 저장한다
- 감사 로그: decision=block, query_type=out_of_scope(권한 외), flags=[SHARE_DENIED_BURST], rule_id=SHARE-DENY-001,
  feature=share.view. 질의·문서는 없음(AI 요청이 아님). 응답은 그대로 404(존재 여부 노출 금지)
"""
import logging
import time
import uuid

from app.auth import CurrentUser
from app.core.context import get_request_id
from app.db import SessionLocal
from app.features.ratelimit.store import PostgresStore
from app.models import AuditLog
from app.models.audit import TEST_SESSION_PREFIX

log = logging.getLogger("nesume.share")

WINDOW_SECONDS = 600
THRESHOLD = 5
FLAG = "SHARE_DENIED_BURST"
RULE_ID = "SHARE-DENY-001"
FEATURE = "share.view"


def _request_uuid() -> uuid.UUID:
    rid = get_request_id()
    try:
        return uuid.UUID(rid)
    except (TypeError, ValueError):
        return uuid.uuid4()


def record_denied(user: CurrentUser, *, now: float | None = None) -> bool:
    """거부 1회를 센다. 이번 시도로 기준(10분 5회)에 닿았으면 감사 로그를 남기고 True."""
    now = time.time() if now is None else now
    key = f"share-deny:{user.sub}"
    try:
        with SessionLocal.begin() as db:
            store = PostgresStore(db)
            store.add(key, 1, window_seconds=WINDOW_SECONDS, now=now)
            count, _ = store.get(key, window_seconds=WINDOW_SECONDS, now=now)
            if count != THRESHOLD:
                return False
            is_test = bool(getattr(user, "is_test", False))
            db.add(AuditLog(
                request_id=_request_uuid(), session_id=f"{TEST_SESSION_PREFIX}share" if is_test else "",
                user_id=user.sub, role=str(user.role), feature=FEATURE, query_type="out_of_scope",
                flags=[FLAG], rule_id=RULE_ID, decision="block", is_test=is_test,
            ))
        log.warning("share_access_denied_burst", extra={"fields": {"user_id": user.sub, "count": count}})
        return True
    except Exception:  # 감시 실패가 응답(404)을 바꾸면 안 된다
        log.exception("share_denied_record_failed")
        return False
