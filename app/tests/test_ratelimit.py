"""C7 레이트리밋 테스트 — 순수 판정(rules) + 서비스(InMemoryStore). DB 없이 실행."""
from app.features.ratelimit.policy import Limit, RateLimits, load_limits
from app.features.ratelimit.rules import evaluate
from app.features.ratelimit.service import RateLimiter
from app.features.ratelimit.store import InMemoryStore

_LIM = Limit("x", max_count=3, window_seconds=60)


# --- rules (순수) ---------------------------------------------------------

def test_under_limit_allowed():
    assert evaluate(_LIM, count=0, elapsed=0).allowed
    assert evaluate(_LIM, count=2, elapsed=10).allowed


def test_at_or_over_limit_denied_with_retry():
    d = evaluate(_LIM, count=3, elapsed=10)   # 한도 도달 → 거부(fail-safe)
    assert not d.allowed
    assert d.retry_after == 50                # 창 60 - 경과 10

    d2 = evaluate(_LIM, count=9, elapsed=59.2)
    assert not d2.allowed
    assert d2.retry_after == 1                # ceil(60-59.2)


def test_window_elapsed_allows_even_if_count_high():
    # 창이 이미 지났으면(elapsed>=window) 리셋된 것 → 허용(방어적)
    assert evaluate(_LIM, count=99, elapsed=60).allowed


# --- 한도 로드 ------------------------------------------------------------

def test_load_limits_defaults(monkeypatch):
    monkeypatch.delenv("RL_REQUESTS_PER_MIN", raising=False)
    lims = load_limits()
    assert lims.requests_per_min.max_count == 60
    assert lims.tokens_per_day.window_seconds == 86_400
    assert lims.exfil_per_session.max_count == 5


def test_env_override_and_bad_value(monkeypatch):
    monkeypatch.setenv("RL_REQUESTS_PER_MIN", "10")
    monkeypatch.setenv("RL_TOKENS_PER_DAY", "0")      # 0 이하는 무시 → 기본값
    monkeypatch.setenv("RL_EXFIL_VIOLATIONS", "abc")  # 파싱불가 → 기본값
    lims = load_limits()
    assert lims.requests_per_min.max_count == 10
    assert lims.tokens_per_day.max_count == 100_000
    assert lims.exfil_per_session.max_count == 5


# --- 서비스 (InMemoryStore) ----------------------------------------------

def _limiter() -> RateLimiter:
    limits = RateLimits(
        requests_per_min=Limit("req", 3, 60),
        tokens_per_day=Limit("tok", 100, 86_400),
        exfil_per_session=Limit("exfil", 2, 600),
    )
    return RateLimiter(InMemoryStore(), limits)


def test_requests_per_min_blocks_after_limit():
    rl = _limiter()
    assert rl.check_request("u", now=0).allowed       # 1
    assert rl.check_request("u", now=1).allowed        # 2
    assert rl.check_request("u", now=2).allowed        # 3
    d = rl.check_request("u", now=3)                    # 4 → 거부
    assert not d.allowed and d.retry_after == 57       # 60 - 3


def test_requests_reset_next_window():
    rl = _limiter()
    for t in range(3):
        rl.check_request("u", now=t)
    assert not rl.check_request("u", now=5).allowed    # 같은 창 거부
    assert rl.check_request("u", now=61).allowed       # 다음 창 허용


def test_requests_per_user_isolated():
    rl = _limiter()
    for t in range(3):
        rl.check_request("a", now=t)
    assert not rl.check_request("a", now=4).allowed    # a는 소진
    assert rl.check_request("b", now=4).allowed        # b는 별개


def test_token_budget_precheck_then_record():
    rl = _limiter()
    assert rl.check_tokens("u", now=0).allowed         # 아직 0
    rl.record_tokens("u", 100, now=1)                  # 일일 한도 100 소진
    d = rl.check_tokens("u", now=2)
    assert not d.allowed                               # 초과 → LLM 전 거부


def test_exfil_session_block_after_threshold():
    rl = _limiter()
    assert rl.check_session("s", now=0).allowed        # 위반 0
    rl.record_violation("s", now=1)
    rl.record_violation("s", now=2)                    # 2회 = 임계치
    d = rl.check_session("s", now=3)
    assert not d.allowed                               # 세션 LLM 차단
    assert d.retry_after == 598                         # 창은 첫 위반(now=1) 시작 → 600 - 경과 2


def test_exfil_block_lifts_after_window():
    rl = _limiter()
    rl.record_violation("s", now=0)
    rl.record_violation("s", now=1)
    assert not rl.check_session("s", now=2).allowed    # 차단 중
    assert rl.check_session("s", now=601).allowed      # 창 지나 해제
