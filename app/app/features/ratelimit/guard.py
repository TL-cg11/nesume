"""C7 — 가드레일(A8)을 감싸는 레이트리밋 래퍼.

LLM을 쓰는 엔드포인트는 모두 `Depends(get_guardrail)`로 가드레일을 받는다. 그 공급 지점이
이 래퍼를 돌려주므로 **라우터를 고치지 않아도 전부 덮이고**, 새 기능도 빠질 수 없다(docs/C7.md).

순서 (`run`·`run_split` 같음):
    1. 예외: role=system(배치) · 서버 설정 `RL_EXEMPT_USERS`의 평가 계정
       ★ `ctx.is_test`로는 빼지 않는다 — 지금은 클라이언트 헤더로 정해져 누구나 붙일 수 있다
    2. 탈취 누적: 세션 기준 → 사용자 기준 (둘 중 하나라도 차단 중이면 거부)
    3. 요청/분 → 토큰/일
    4. 가드레일 실행
    5. 사용 토큰 누적, 판정이 block·exfiltration이면 세션·사용자 위반 1 증가

저장소 오류는 **허용(fail-open)하고 경고 로그**를 남긴다. 레이트리밋 장애로 LLM 기능 전체가 멈추지
않게 — 탈취 차단은 A3·A8이 요청마다 따로 하므로 이 층이 잠깐 빠져도 보호가 사라지지 않는다.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import TYPE_CHECKING, Any

from app.core.errors import RateLimitedError
from app.features.ratelimit.policy import RateLimits, load_limits
from app.features.ratelimit.rules import Decision
from app.features.ratelimit.service import RateLimiter
from app.features.ratelimit.store import PostgresStore, RateLimitStore

if TYPE_CHECKING:
    from app.guardrail.pipeline import Guardrail, PartsBuilder, PipelineResult, RequestContext

log = logging.getLogger("nesume.ratelimit")

#: 거부 안내. 어떤 한도에 걸렸는지는 알리지 않는다 — 탈취 누적 차단인지 드러나면 우회를 돕는다
LIMITED_MESSAGE = "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요."

StoreFactory = Callable[[], AbstractContextManager[RateLimitStore]]


@contextmanager
def postgres_store() -> Iterator[RateLimitStore]:
    """호출마다 짧은 트랜잭션(감사 로그 `DbAuditSink`와 같은 방식). 요청 세션에 묶이지 않는다."""
    from app.db import SessionLocal

    with SessionLocal() as db:
        yield PostgresStore(db)
        db.commit()


class RateLimitedGuardrail:
    """`Guardrail`과 같은 `run`·`run_split`을 제공하고, 앞뒤로 C7 한도를 건다."""

    def __init__(
        self,
        inner: Guardrail,
        *,
        store_factory: StoreFactory = postgres_store,
        limits: RateLimits | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.inner = inner
        self.limits = limits or load_limits()
        self._store_factory = store_factory
        self._clock = clock

    async def run(self, query: str, ctx: RequestContext) -> PipelineResult:
        return await self._guarded(ctx, lambda: self.inner.run(query, ctx))

    async def run_split(self, query: str, ctx: RequestContext, *, parts: PartsBuilder) -> PipelineResult:
        return await self._guarded(ctx, lambda: self.inner.run_split(query, ctx, parts=parts))

    def __getattr__(self, name: str) -> Any:
        # llm·canaries 등 나머지 속성은 원래 가드레일 것을 그대로 보인다
        return getattr(self.inner, name)

    # ------------------------------------------------------------------

    def _exempt(self, ctx: RequestContext) -> bool:
        return ctx.role == "system" or ctx.user_id in self.limits.exempt_users

    async def _guarded(
        self, ctx: RequestContext, call: Callable[[], Awaitable[PipelineResult]]
    ) -> PipelineResult:
        if self._exempt(ctx):
            return await call()

        denied = await self._with_store(lambda limiter: _precheck(limiter, ctx, self._clock()))
        if denied is not None:
            raise RateLimitedError(LIMITED_MESSAGE, headers={"Retry-After": str(denied.retry_after)})

        result = await call()
        await self._with_store(lambda limiter: _record(limiter, ctx, result, self._clock()))
        return result

    async def _with_store(self, fn: Callable[[RateLimiter], Decision | None]) -> Decision | None:
        """저장소를 열어 `fn`을 돌린다. 저장소 오류면 경고만 남기고 None(= 허용)."""

        def work() -> Decision | None:
            with self._store_factory() as store:
                return fn(RateLimiter(store, self.limits))

        try:
            return await asyncio.to_thread(work)
        except Exception:  # noqa: BLE001 — 어떤 저장소 오류든 fail-open
            log.warning("rate limit store unavailable, allowing request", exc_info=True)
            return None


def _precheck(limiter: RateLimiter, ctx: RequestContext, now: float) -> Decision | None:
    """거부할 판정을 돌려준다. 통과면 None. 요청/분은 여기서 1 증가한다."""
    checks: list[Callable[[], Decision]] = []
    if ctx.session_id:
        checks.append(lambda: limiter.check_session(ctx.session_id, now=now))
    checks += [
        lambda: limiter.check_user(ctx.user_id, now=now),
        lambda: limiter.check_request(ctx.user_id, now=now),
        lambda: limiter.check_tokens(ctx.user_id, now=now),
    ]
    for check in checks:
        decision = check()
        if not decision.allowed:
            return decision
    return None


def _record(limiter: RateLimiter, ctx: RequestContext, result: PipelineResult, now: float) -> None:
    limiter.record_tokens(ctx.user_id, result.usage.total_tokens, now=now)
    if result.blocked and result.verdict.query_type == "exfiltration":
        if ctx.session_id:
            limiter.record_violation(ctx.session_id, now=now)
        limiter.record_user_violation(ctx.user_id, now=now)
