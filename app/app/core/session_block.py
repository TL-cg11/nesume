"""D16 — 세션 자동 차단 (docs/ops/alerts.md 3장, docs/policy/block-policy.md 6장).

두 부분이다.

1. 차단 목록 저장소(`blocked_sessions`, models/blocked_session.py):
`block()`·`release()`·`active_block()`·`list_blocks()`.
   운영자 API(auth/admin_sessions.py)와 아래 래퍼가 같이 쓴다.
2. `SessionBlockGuardrail`: C7 `RateLimitedGuardrail` 안쪽에 끼는 래퍼. `get_guardrail()` 이 이것을
돌려주므로
   LLM 경로 전부가 지나간다(라우터 수정 없음, C7 과 같은 방식).

    앞: 세션이 차단 목록에 있으면 429(C7 세션 제한과 같은 응답·문구 — 어떤 차단인지 드러내지 않는다)
    뒤: 판정을 보고
        - 카나리 적중(verdict.canary_hit) → canary_hit 알림 + 세션 차단(운영자가 풀 때까지)
        - 탈취 판정(block·exfiltration)으로 C7 세션 임계치에 **막 도달** → exfil_threshold 알림 +
        차단(제한 시간만큼)
          C7 이 제한 시간 동안 이미 429 를 주므로 기능상 중복이지만, 목록에 남아야 운영자가 보고 알림이 한
          번만 간다.

★ 저장소 오류는 **허용(fail-open)하고 경고 로그**. 차단 목록 장애로 LLM 기능 전체가 멈추지 않게(C7 과 같은
판단).
  카나리·탈취는 A5·A3 가 요청마다 따로 막으므로 이 층이 잠깐 빠져도 유출이 열리지는 않는다.
★ 세션이 없는 요청(session_id 빈 값)은 차단할 대상이 없다. 알림만 보낸다.
★ 평가 트래픽(is_test, `test-` 접두어)은 차단하지 않는다(블록 정책 6장. 러너가 카나리 시나리오를 돌리면
바로 막힌다).
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.alerts import Alerts, alerts
from app.core.errors import RateLimitedError
from app.models.blocked_session import BLOCK_REASONS, SYSTEM_ACTOR, BlockedSession

if TYPE_CHECKING:
    from app.guardrail.pipeline import PartsBuilder, PipelineResult, RequestContext

log = logging.getLogger("nesume.session_block")

#: C7 과 같은 문구. 어떤 한도·차단에 걸렸는지 알리지 않는다
LIMITED_MESSAGE = "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요."
#: 만료 없는 차단의 Retry-After(초). 클라이언트에 "언제 풀린다"를 약속하지 않는 값이면 된다
INDEFINITE_RETRY_AFTER = 3600


# --------------------------------------------------------------------------
# 저장소
# --------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime) -> datetime:
    """tz 없는 값은 UTC 로 본다(테스트용 SQLite 가 tz 를 버린다. Postgres 는 timestamptz 라 항상 aware)."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def is_active(row: BlockedSession, now: datetime) -> bool:
    return row.released_at is None and (row.expires_at is None or _aware(row.expires_at) > now)


def active_block(db: Session, session_id: str, *, now: datetime | None = None) -> BlockedSession | None:
    """지금 유효한 차단 행. 없거나 해제됐거나 만료됐으면 None."""
    row = db.get(BlockedSession, session_id)
    if row is None or not is_active(row, now or _now()):
        return None
    return row


def block(
    db: Session,
    session_id: str,
    *,
    user_id: str,
    reason: str,
    rule_id: str | None = None,
    note: str | None = None,
    blocked_by: str = SYSTEM_ACTOR,
    expires_at: datetime | None = None,
    now: datetime | None = None,
) -> tuple[BlockedSession, bool]:
    """세션을 차단한다. 돌려주는 둘째 값은 **새로 차단했는가**(이미 유효한 차단이 있으면 False — 알림 중복
    방지).

    이미 차단 중이면 더 센 쪽으로 갱신만 한다: 만료 있는 차단 위에 만료 없는 차단이 오면 만료를 지운다.
    """
    if reason not in BLOCK_REASONS:
        raise ValueError(f"reason 은 {BLOCK_REASONS} 중 하나여야 합니다: {reason!r}")
    now = now or _now()
    row = db.get(BlockedSession, session_id)
    if row is None:
        row = BlockedSession(session_id=session_id, user_id=user_id)
        db.add(row)
    elif active_block(db, session_id, now=now) is not None:
        if expires_at is None and row.expires_at is not None:
            row.expires_at = None
            row.reason, row.rule_id, row.blocked_by = reason, rule_id, blocked_by
        return row, False
    row.user_id = user_id
    row.reason = reason
    row.rule_id = rule_id
    row.note = note
    row.blocked_by = blocked_by
    row.expires_at = expires_at
    row.released_at = None
    row.released_by = None
    row.created_at = now
    db.flush()
    return row, True


def release(
    db: Session, session_id: str, *, released_by: str, now: datetime | None = None
) -> BlockedSession | None:
    """차단을 푼다. 유효한 차단이 없으면 None."""
    row = active_block(db, session_id, now=now)
    if row is None:
        return None
    row.released_at = now or _now()
    row.released_by = released_by
    db.flush()
    return row


def list_blocks(
    db: Session, *, active_only: bool = True, limit: int = 200, now: datetime | None = None
) -> list[BlockedSession]:
    """최근 차단 목록. `active_only` 면 지금 유효한 것만."""
    now = now or _now()
    stmt = select(BlockedSession).order_by(BlockedSession.created_at.desc()).limit(limit)
    rows = list(db.execute(stmt).scalars())
    if active_only:
        rows = [r for r in rows if is_active(r, now)]
    return rows


# --------------------------------------------------------------------------
# 가드레일 래퍼
# --------------------------------------------------------------------------

SessionFactory = Callable[[], AbstractContextManager[Session]]


@contextmanager
def db_session() -> Iterator[Session]:
    """호출마다 짧은 트랜잭션(C7 postgres_store 와 같은 방식)."""
    from app.db import SessionLocal

    with SessionLocal() as db:
        yield db
        db.commit()


class SessionBlockGuardrail:
    """`Guardrail` 과 같은 `run`·`run_split` 을 제공하고, 앞에서 차단 목록을 보고 뒤에서 자동 차단한다."""

    def __init__(
        self,
        inner: Any,
        *,
        session_factory: SessionFactory = db_session,
        publisher: Alerts | None = None,
        clock: Callable[[], float] = time.time,
        exfil_limit_reached: Callable[[str], int | None] | None = None,
    ) -> None:
        """
        exfil_limit_reached(session_id) → 제한 중이면 남은 초, 아니면 None. 기본은 C7 저장소를 읽는다.
        테스트에서 갈아 끼운다.
        """
        self.inner = inner
        self._session_factory = session_factory
        self._publisher = publisher or alerts
        self._clock = clock
        self._exfil_limit_reached = exfil_limit_reached or self._c7_limit_reached

    async def run(self, query: str, ctx: RequestContext, **kwargs: Any) -> PipelineResult:
        # 추가 키워드 인자(A #18 `prompt=` 등)는 그대로 안쪽에 넘긴다(C7 #71 과 같은 방식)
        return await self._guarded(ctx, lambda: self.inner.run(query, ctx, **kwargs))

    async def run_split(
        self, query: str, ctx: RequestContext, *, parts: PartsBuilder, **kwargs: Any
    ) -> PipelineResult:
        return await self._guarded(ctx, lambda: self.inner.run_split(query, ctx, parts=parts, **kwargs))

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    # ------------------------------------------------------------------

    def _skip(self, ctx: RequestContext) -> bool:
        return ctx.role == "system" or ctx.is_test or not ctx.session_id

    async def _guarded(
        self, ctx: RequestContext, call: Callable[[], Awaitable[PipelineResult]]
    ) -> PipelineResult:
        if not self._skip(ctx):
            retry_after = await self._with_db(lambda db: self._retry_after(db, ctx.session_id))
            if retry_after is not None:
                raise RateLimitedError(LIMITED_MESSAGE, headers={"Retry-After": str(retry_after)})

        result = await call()
        await self._after(ctx, result)
        return result

    def _retry_after(self, db: Session, session_id: str) -> int | None:
        now = datetime.fromtimestamp(self._clock(), tz=UTC)
        row = active_block(db, session_id, now=now)
        if row is None:
            return None
        if row.expires_at is None:
            return INDEFINITE_RETRY_AFTER
        return max(1, int((_aware(row.expires_at) - now).total_seconds()))

    async def _after(self, ctx: RequestContext, result: PipelineResult) -> None:
        verdict = result.verdict
        if verdict.canary_hit:
            await self._auto_block(
                ctx, reason="canary_hit", rule_id=verdict.rule_id or "LEAK_CANARY", expires_in=None,
                summary=f"카나리 적중: feature={ctx.feature} stage={verdict.stage} rule={verdict.rule_id}",
                severity="critical",
            )
            return
        if result.blocked and verdict.query_type == "exfiltration" and not self._skip(ctx):
            remaining = await asyncio.to_thread(self._safe_limit_reached, ctx.session_id)
            if remaining:
                await self._auto_block(
                    ctx, reason="exfil_threshold", rule_id=verdict.rule_id, expires_in=remaining,
                    summary=f"탈취 세션 제한 임계치 도달: feature={ctx.feature} rule={verdict.rule_id} "
                            f"제한 {remaining}s",
                    severity="warn",
                )

    async def _auto_block(
        self, ctx: RequestContext, *, reason: str, rule_id: str | None, expires_in: int | None,
        summary: str, severity: str,
    ) -> None:
        if self._skip(ctx):
            # 차단할 세션이 없다(세션 없음·평가 트래픽·system). 알림은 보낸다 — 카나리는 어떤 경우든 보안
            # 이벤트다
            if reason == "canary_hit":
                self._publisher.emit(reason, summary, severity=severity, user_id=ctx.user_id,
                                     request_id=str(ctx.request_id))
            return

        now = datetime.fromtimestamp(self._clock(), tz=UTC)
        expires_at = now + timedelta(seconds=expires_in) if expires_in else None

        def work(db: Session) -> bool:
            _, created = block(
                db, ctx.session_id, user_id=ctx.user_id, reason=reason, rule_id=rule_id,
                expires_at=expires_at, now=now,
            )
            return created

        created = await self._with_db(work)
        if created is None:
            # 저장소 오류. 차단은 못 했지만 알림은 보낸다 — 사람이 보고 수동 차단할 수 있게
            summary += " (차단 목록 저장 실패 — 수동 차단 필요)"
        elif not created:
            return  # 이미 차단 중. 알림 중복 안 함
        self._publisher.emit(
            reason, summary, severity=severity, session_id=ctx.session_id, user_id=ctx.user_id,
            request_id=str(ctx.request_id),
        )

    async def _with_db(self, fn: Callable[[Session], Any]) -> Any:
        """저장소를 열어 `fn` 을 돌린다. 오류면 경고만 남기고 None(= 허용)."""

        def work() -> Any:
            with self._session_factory() as db:
                return fn(db)

        try:
            return await asyncio.to_thread(work)
        except Exception:  # noqa: BLE001 — 어떤 저장소 오류든 fail-open
            log.warning("blocked session store unavailable, allowing request", exc_info=True)
            return None

    def _safe_limit_reached(self, session_id: str) -> int | None:
        try:
            return self._exfil_limit_reached(session_id)
        except Exception:  # noqa: BLE001
            log.warning("exfil limit lookup failed", exc_info=True)
            return None

    def _c7_limit_reached(self, session_id: str) -> int | None:
        """이번 탈취 위반으로 C7 세션 임계치에 **도달하는지**. 도달하면 남은 제한 초, 아니면 None.

        이 래퍼는 C7 래퍼 **안쪽**이라(fastapi.py `_limited`) C7 `_record` 가 아직 돌기 전이다.
        그래서 저장소의 현재 창 누적에 이번 위반 1을 더해 본다. 키·창은 C7 `record_violation` 과 같다.
        """
        from app.features.ratelimit.guard import postgres_store
        from app.features.ratelimit.policy import load_limits

        lim = load_limits().exfil_per_session
        with postgres_store() as store:
            count, elapsed = store.get(
                f"exfil:{session_id}", window_seconds=lim.window_seconds, now=self._clock()
            )
        if count + 1 < lim.max_count:
            return None
        return max(1, int(lim.window_seconds - elapsed))


__all__ = [
    "LIMITED_MESSAGE",
    "SessionBlockGuardrail",
    "active_block",
    "block",
    "db_session",
    "is_active",
    "list_blocks",
    "release",
]
