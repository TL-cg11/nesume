"""C7 LLM 경로 배선 — 가드레일 래퍼(`RateLimitedGuardrail`). DB 없이 InMemoryStore로 본다.

docs/C7.md "LLM 경로 배선" 테스트 목록.
"""
from __future__ import annotations

import asyncio
import re
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.core.errors import RateLimitedError, register_exception_handlers
from app.features.ratelimit.guard import RateLimitedGuardrail
from app.features.ratelimit.policy import Limit, RateLimits
from app.features.ratelimit.store import InMemoryStore
from app.guardrail.llm_client import Usage
from app.guardrail.pipeline import PipelineResult, RequestContext
from app.guardrail.schema import Verdict

ALLOW = Verdict("allow", "output_guard")
EXFIL = Verdict("block", "classifier", query_type="exfiltration")


class FakeGuard:
    """정해 둔 판정·토큰을 돌려주고 호출 수를 센다."""

    def __init__(self, verdict: Verdict = ALLOW, tokens: int = 10) -> None:
        self.verdict = verdict
        self.tokens = tokens
        self.calls = 0
        self.canaries = ("x",)

    async def run(self, query, ctx):
        self.calls += 1
        return PipelineResult(
            text="", verdict=self.verdict, usage=Usage(input_tokens=self.tokens, output_tokens=0, model="m")
        )

    async def run_split(self, query, ctx, *, parts):
        return await self.run(query, ctx)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def limits(**kw) -> RateLimits:
    base = dict(
        requests_per_min=Limit("requests_per_min", 100, 60),
        tokens_per_day=Limit("tokens_per_day", 1000, 86_400),
        exfil_per_session=Limit("exfil_per_session", 5, 600),
        exfil_per_user=Limit("exfil_per_user", 10, 3600),
    )
    base.update(kw)
    return RateLimits(**base)


def make(inner=None, *, store=None, **kw):
    store = store or InMemoryStore()

    @contextmanager
    def factory():
        yield store

    clock = Clock()
    guard = RateLimitedGuardrail(
        inner or FakeGuard(), store_factory=factory, limits=limits(**kw), clock=clock
    )
    return guard, store, clock


def ctx(user="u1", session="s1", role="user", is_test=False) -> RequestContext:
    sid = f"test-{session}" if is_test else session
    return RequestContext(user_id=user, role=role, feature="f", session_id=sid, is_test=is_test)


def run(guard, c=None):
    return asyncio.run(guard.run("q", c or ctx()))


def test_within_limits_passes_and_records_tokens():
    inner = FakeGuard(tokens=7)
    guard, store, _ = make(inner)
    run(guard)
    assert inner.calls == 1
    assert store.get("tok:u1", window_seconds=86_400, now=1000)[0] == 7  # Usage.total_tokens와 같다


def test_requests_per_min_exceeded_is_429_with_retry_after():
    inner = FakeGuard()
    guard, _, clock = make(inner, requests_per_min=Limit("requests_per_min", 2, 60))
    run(guard)
    clock.now += 10
    run(guard)
    with pytest.raises(RateLimitedError) as e:
        run(guard)
    assert e.value.status_code == 429
    assert e.value.headers == {"Retry-After": "50"}
    assert inner.calls == 2  # 거부된 요청은 LLM을 부르지 않는다


def test_tokens_per_day_exceeded():
    guard, _, _ = make(FakeGuard(tokens=600), tokens_per_day=Limit("tokens_per_day", 1000, 86_400))
    run(guard)
    run(guard)  # 1200 누적
    with pytest.raises(RateLimitedError):
        run(guard)


def test_five_exfil_blocks_that_session_only():
    guard, _, _ = make(FakeGuard(verdict=EXFIL))
    for _ in range(5):
        run(guard, ctx(session="s1"))
    with pytest.raises(RateLimitedError):
        run(guard, ctx(session="s1"))
    run(guard, ctx(session="s2"))  # 세션 기준 5회는 사용자를 잠그지 않는다


def test_rotating_session_ids_hits_user_limit():
    guard, _, _ = make(FakeGuard(verdict=EXFIL))
    for i in range(10):
        run(guard, ctx(session=f"s{i}"))  # 세션마다 1회 — 세션 기준엔 안 걸린다
    with pytest.raises(RateLimitedError):
        run(guard, ctx(session="fresh"))


def test_exfil_without_session_still_counts_for_user():
    guard, _, _ = make(FakeGuard(verdict=EXFIL))
    for _ in range(10):
        run(guard, ctx(session=""))
    with pytest.raises(RateLimitedError):
        run(guard, ctx(session=""))


def test_system_role_and_registered_eval_account_are_exempt():
    guard, _, _ = make(
        requests_per_min=Limit("requests_per_min", 1, 60), exempt_users=frozenset({"eval-runner"})
    )
    for _ in range(3):
        run(guard, ctx(user="batch", role="system"))
        run(guard, ctx(user="eval-runner"))


def test_is_test_header_does_not_exempt():
    guard, _, _ = make(requests_per_min=Limit("requests_per_min", 1, 60))
    run(guard, ctx(is_test=True))
    with pytest.raises(RateLimitedError):
        run(guard, ctx(is_test=True))  # test- 세션 접두어는 누구나 붙일 수 있다


def test_store_error_fails_open():
    @contextmanager
    def broken():
        raise RuntimeError("db down")
        yield  # pragma: no cover

    inner = FakeGuard()
    guard = RateLimitedGuardrail(inner, store_factory=broken, limits=limits())
    run(guard)
    assert inner.calls == 1


def test_run_split_is_limited_too():
    guard, _, _ = make(requests_per_min=Limit("requests_per_min", 1, 60))
    asyncio.run(guard.run_split("q", ctx(), parts=lambda t: [t]))
    with pytest.raises(RateLimitedError):
        asyncio.run(guard.run_split("q", ctx(), parts=lambda t: [t]))


def test_other_attributes_come_from_inner():
    guard, _, _ = make()
    assert guard.canaries == ("x",)


def test_retry_after_header_reaches_response():
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/x")
    def _x():
        raise RateLimitedError("많음", headers={"Retry-After": "30"})

    r = TestClient(app).get("/x")
    assert r.status_code == 429
    assert r.headers["retry-after"] == "30"
    assert r.json()["code"] == "rate_limited"


# --- 배선: 모든 LLM 엔드포인트가 래퍼를 받는지 ---------------------------------


def test_get_guardrail_returns_the_wrapper():
    from app.guardrail.fastapi import get_guardrail

    assert isinstance(get_guardrail(), RateLimitedGuardrail)


def _api_routes(routes):
    # FastAPI 0.142부터 include_router가 라우터를 감싼다(`original_router`) — 안쪽까지 내려간다
    for r in routes:
        if isinstance(r, APIRoute):
            yield r
        inner = getattr(r, "original_router", None)
        if inner is not None:
            yield from _api_routes(inner.routes)


def _calls(dependant):
    for d in dependant.dependencies:
        yield d.call
        yield from _calls(d)


def test_llm_endpoints_all_depend_on_get_guardrail():
    from app.guardrail.fastapi import _shared, get_guardrail
    from app.main import app

    routes = list(_api_routes(app.routes))
    using = [r.path for r in routes if get_guardrail in set(_calls(r.dependant))]
    assert len(using) >= 7  # 매칭 1·문체 1·GitHub 1·글쓰기 4 (10-30)
    assert not [r.path for r in routes if _shared in set(_calls(r.dependant))]


def test_no_guardrail_built_outside_guardrail_package():
    """기능 코드가 `Guardrail(`을 직접 만들면 래퍼를 건너뛴다. tests/는 dependency_overrides용이라 제외."""
    root = Path(__file__).resolve().parents[1] / "app"
    pattern = re.compile(r"\bGuardrail\(")
    hits = [
        str(p.relative_to(root))
        for p in root.rglob("*.py")
        if "guardrail" not in p.relative_to(root).parts[:1] and pattern.search(p.read_text(encoding="utf-8"))
    ]
    assert hits == []
