"""C7 — 레이트리밋 오케스트레이션 (store + rules 조립).

docs/C7.md 배선:  LLM 경로 앞 `check_*` → (통과면) A8 호출 → 뒤 `record_*`.
A8은 안 건드리고 그 앞뒤에 얇게 붙는다. `now`는 호출측 주입(미들웨어/의존성이 time.time).

- 비용 쿼터: `check_request`(요청/분) · `check_tokens`/`record_tokens`(토큰/일, 선체크·후기록).
- 탈취 세션 제한: `check_session`(차단 중인가) · `record_violation`(A8 판정=block[exfil]일 때).
- 탈취 사용자 제한: `check_user`·`record_user_violation` — 세션을 바꿔 가며 우회하는 경우의 방어선.
"""
from __future__ import annotations

from app.features.ratelimit.policy import RateLimits, load_limits
from app.features.ratelimit.rules import Decision, evaluate
from app.features.ratelimit.store import RateLimitStore


class RateLimiter:
    """store·한도를 들고 축별 check/record를 제공. 앱 기동 시 하나 만들어 쓴다."""

    def __init__(self, store: RateLimitStore, limits: RateLimits | None = None) -> None:
        self.store = store
        self.limits = limits or load_limits()

    # --- 비용 쿼터 -----------------------------------------------------------

    def check_request(self, user_id: str, *, now: float) -> Decision:
        """요청/분 한도. 체크 시점에 1 증가(요청 자체가 카운트 대상). 한도 도달이면 거부."""
        lim = self.limits.requests_per_min
        count, elapsed = self.store.get(f"req:{user_id}", window_seconds=lim.window_seconds, now=now)
        decision = evaluate(lim, count=count, elapsed=elapsed)
        if decision.allowed:
            self.store.add(f"req:{user_id}", 1, window_seconds=lim.window_seconds, now=now)
        return decision

    def check_tokens(self, user_id: str, *, now: float) -> Decision:
        """LLM 호출 **전** 일일 토큰 예산 초과 여부(초과면 LLM 비용 안 쓰고 거부)."""
        lim = self.limits.tokens_per_day
        count, elapsed = self.store.get(f"tok:{user_id}", window_seconds=lim.window_seconds, now=now)
        return evaluate(lim, count=count, elapsed=elapsed)

    def record_tokens(self, user_id: str, tokens: int, *, now: float) -> None:
        """LLM 호출 **후** 실제 사용 토큰(A8 `Usage.total_tokens`)을 누적."""
        if tokens <= 0:
            return
        lim = self.limits.tokens_per_day
        self.store.add(f"tok:{user_id}", tokens, window_seconds=lim.window_seconds, now=now)

    # --- 탈취 세션 제한 (spec §418) ------------------------------------------

    def check_session(self, session_id: str, *, now: float) -> Decision:
        """세션이 탈취 누적으로 차단 중인지(차단이면 LLM 경로 거부)."""
        lim = self.limits.exfil_per_session
        count, elapsed = self.store.get(
            f"exfil:{session_id}", window_seconds=lim.window_seconds, now=now
        )
        return evaluate(lim, count=count, elapsed=elapsed)

    def record_violation(self, session_id: str, *, now: float) -> None:
        """A8 판정이 탈취(block, exfiltration)일 때 세션 위반 1 증가."""
        lim = self.limits.exfil_per_session
        self.store.add(f"exfil:{session_id}", 1, window_seconds=lim.window_seconds, now=now)

    # --- 탈취 사용자 제한 (세션 우회 방어선) --------------------------------

    def check_user(self, user_id: str, *, now: float) -> Decision:
        """사용자가 탈취 누적으로 차단 중인지. 세션 기준보다 한도가 느슨하다(정상 사용자 오탐 대비)."""
        lim = self.limits.exfil_per_user
        count, elapsed = self.store.get(
            f"exfil_user:{user_id}", window_seconds=lim.window_seconds, now=now
        )
        return evaluate(lim, count=count, elapsed=elapsed)

    def record_user_violation(self, user_id: str, *, now: float) -> None:
        """A8 판정이 탈취(block, exfiltration)일 때 사용자 위반 1 증가."""
        lim = self.limits.exfil_per_user
        self.store.add(f"exfil_user:{user_id}", 1, window_seconds=lim.window_seconds, now=now)
