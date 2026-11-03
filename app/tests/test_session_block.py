"""D16 세션 자동 차단 — 저장소 함수와 `SessionBlockGuardrail` 래퍼.

Postgres 없이 SQLite 메모리 DB + 가짜 가드레일로 돈다.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.alerts import AlertEvent, Alerts, Transport
from app.core.errors import RateLimitedError
from app.core.session_block import (
    INDEFINITE_RETRY_AFTER,
    SessionBlockGuardrail,
    active_block,
    block,
    list_blocks,
    release,
)
from app.guardrail.llm_client import Usage
from app.guardrail.pipeline import PipelineResult, RequestContext
from app.guardrail.schema import Finding, Verdict, allow
from app.models.blocked_session import BlockedSession

ALLOW = allow("output_guard")
CANARY = Verdict("block", "output_guard", (Finding("LEAK_CANARY", "critical"),))
EXFIL = Verdict("block", "classifier", (Finding("INJ_DIRECT", "critical"),), query_type="exfiltration")
NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


@pytest.fixture
def factory():
    # 래퍼가 스레드에서 저장소를 연다 → 모든 스레드가 같은 메모리 DB 를 보게 StaticPool
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    BlockedSession.__table__.create(engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False)

    @contextmanager
    def open_session():
        with maker() as db:
            yield db
            db.commit()

    yield open_session
    engine.dispose()


class Recorder(Transport):
    name = "rec"

    def __init__(self) -> None:
        self.events: list[AlertEvent] = []

    def send(self, event: AlertEvent) -> None:
        self.events.append(event)


class FakeGuard:
    def __init__(self, verdict: Verdict = ALLOW) -> None:
        self.verdict = verdict
        self.calls = 0
        self.kwargs: list[dict] = []  # 호출마다 받은 추가 키워드 인자

    async def run(self, query, ctx, **kwargs):
        self.calls += 1
        self.kwargs.append(kwargs)
        return PipelineResult(text="", verdict=self.verdict, usage=Usage(1, 0, "m"))

    async def run_split(self, query, ctx, *, parts, **kwargs):
        return await self.run(query, ctx, parts=parts, **kwargs)


def _ctx(session="sess-1", **kw) -> RequestContext:
    base = dict(user_id="u-1", role="user", feature="rewrite", session_id=session)
    base.update(kw)
    return RequestContext(**base)


def _wrap(inner, factory, *, limit=None, clock=None):
    rec = Recorder()
    pub = Alerts(rec, sync=True)
    guard = SessionBlockGuardrail(
        inner, session_factory=factory, publisher=pub, clock=clock or (lambda: NOW.timestamp()),
        exfil_limit_reached=limit or (lambda s: None),
    )
    return guard, rec


# ---------- 저장소 ----------


def test_block_release_and_expiry(factory):
    with factory() as db:
        row, created = block(db, "s1", user_id="u", reason="canary_hit", rule_id="LEAK_CANARY", now=NOW)
        assert created and row.expires_at is None and row.blocked_by == "system"
        # 같은 세션 다시 차단 → 새로 만들지 않는다(알림 중복 방지)
        assert block(db, "s1", user_id="u", reason="canary_hit", now=NOW)[1] is False
        assert active_block(db, "s1", now=NOW) is row
        assert release(db, "s1", released_by="op", now=NOW) is row
        assert active_block(db, "s1", now=NOW) is None
        assert release(db, "s1", released_by="op", now=NOW) is None  # 이미 풀림
        # 해제된 뒤 다시 차단하면 새 차단
        assert block(db, "s1", user_id="u", reason="operator", blocked_by="op", now=NOW)[1] is True

        _, created = block(
            db, "s2", user_id="u", reason="exfil_threshold", expires_at=NOW + timedelta(minutes=10), now=NOW
        )
        assert created
        assert active_block(db, "s2", now=NOW + timedelta(minutes=9)) is not None
        assert active_block(db, "s2", now=NOW + timedelta(minutes=10)) is None  # 만료
        # 만료 있는 차단 위에 만료 없는 차단 → 만료를 지운다
        _, created = block(db, "s2", user_id="u", reason="canary_hit", now=NOW)
        assert created is False and active_block(db, "s2", now=NOW).expires_at is None

        assert {r.session_id for r in list_blocks(db, now=NOW)} == {"s1", "s2"}
        release(db, "s1", released_by="op", now=NOW)
        assert {r.session_id for r in list_blocks(db, now=NOW)} == {"s2"}
        assert {r.session_id for r in list_blocks(db, active_only=False, now=NOW)} == {"s1", "s2"}


def test_block_rejects_unknown_reason(factory):
    with factory() as db, pytest.raises(ValueError):
        block(db, "s", user_id="u", reason="whatever")


# ---------- 래퍼 ----------


def test_blocked_session_gets_429_before_inner(factory):
    inner = FakeGuard()
    guard, _ = _wrap(inner, factory)
    with factory() as db:
        block(db, "sess-1", user_id="u-1", reason="operator", blocked_by="op", now=NOW)
    with pytest.raises(RateLimitedError) as exc:
        asyncio.run(guard.run("q", _ctx()))
    assert exc.value.headers["Retry-After"] == str(INDEFINITE_RETRY_AFTER)
    assert inner.calls == 0
    # 다른 세션은 통과
    asyncio.run(guard.run("q", _ctx("sess-2")))
    assert inner.calls == 1


def test_expiring_block_reports_remaining_seconds(factory):
    guard, _ = _wrap(FakeGuard(), factory)
    with factory() as db:
        block(
            db, "sess-1", user_id="u-1", reason="exfil_threshold",
            expires_at=NOW + timedelta(seconds=90), now=NOW,
        )
    with pytest.raises(RateLimitedError) as exc:
        asyncio.run(guard.run("q", _ctx()))
    assert exc.value.headers["Retry-After"] == "90"


def test_canary_hit_blocks_session_and_alerts_once(factory):
    guard, rec = _wrap(FakeGuard(CANARY), factory)
    asyncio.run(guard.run("q", _ctx()))
    with factory() as db:
        row = active_block(db, "sess-1", now=NOW)
        assert row is not None and row.reason == "canary_hit" and row.rule_id == "LEAK_CANARY"
        assert row.expires_at is None  # 운영자가 풀 때까지
    assert [e.type for e in rec.events] == ["canary_hit"]
    assert rec.events[0].session_id == "sess-1" and rec.events[0].user_id == "u-1"
    # 같은 세션의 다음 요청은 429 이고 알림은 다시 가지 않는다
    with pytest.raises(RateLimitedError):
        asyncio.run(guard.run("q", _ctx()))
    assert len(rec.events) == 1


def test_canary_without_session_alerts_but_cannot_block(factory):
    guard, rec = _wrap(FakeGuard(CANARY), factory)
    asyncio.run(guard.run("q", _ctx(session="")))
    assert [e.type for e in rec.events] == ["canary_hit"] and rec.events[0].session_id is None
    with factory() as db:
        assert list_blocks(db, now=NOW) == []


def test_test_traffic_is_never_blocked(factory):
    guard, rec = _wrap(FakeGuard(CANARY), factory)
    asyncio.run(guard.run("q", _ctx(session="test-run", is_test=True)))
    with factory() as db:
        assert list_blocks(db, now=NOW) == []
    assert [e.type for e in rec.events] == ["canary_hit"]  # 보안 이벤트 자체는 알린다


def test_exfil_block_without_threshold_does_nothing(factory):
    guard, rec = _wrap(FakeGuard(EXFIL), factory)
    asyncio.run(guard.run("q", _ctx()))
    with factory() as db:
        assert list_blocks(db, now=NOW) == []
    assert rec.events == []


def test_exfil_threshold_blocks_for_remaining_window(factory):
    guard, rec = _wrap(FakeGuard(EXFIL), factory, limit=lambda s: 600)
    asyncio.run(guard.run("q", _ctx()))
    with factory() as db:
        row = active_block(db, "sess-1", now=NOW)
        assert row.reason == "exfil_threshold" and row.expires_at is not None
        assert active_block(db, "sess-1", now=NOW + timedelta(seconds=601)) is None
    assert [e.type for e in rec.events] == ["exfil_threshold"]
    # 제한 중 재요청은 429, 알림 1회
    with pytest.raises(RateLimitedError):
        asyncio.run(guard.run("q", _ctx()))
    assert len(rec.events) == 1


def test_store_failure_is_fail_open_and_still_alerts(factory):
    @contextmanager
    def broken():
        raise RuntimeError("db down")
        yield  # pragma: no cover

    inner = FakeGuard(CANARY)
    guard, rec = _wrap(inner, broken)
    asyncio.run(guard.run("q", _ctx()))  # 예외 없음
    assert inner.calls == 1
    assert len(rec.events) == 1 and "수동 차단 필요" in rec.events[0].summary


def test_system_role_bypasses(factory):
    inner = FakeGuard()
    guard, _ = _wrap(inner, factory)
    with factory() as db:
        block(db, "sess-1", user_id="u-1", reason="operator", blocked_by="op", now=NOW)
    asyncio.run(guard.run("q", _ctx(role="system")))
    assert inner.calls == 1


def test_run_passes_extra_kwargs_to_inner(factory):
    """A #18: guard.run(query, ctx, prompt=build) — 래퍼가 인자를 삼키면 TypeError."""
    inner = FakeGuard()
    guard, _ = _wrap(inner, factory)

    def build(text):
        return f"<p>{text}</p>"

    asyncio.run(guard.run("q", _ctx(), prompt=build))
    assert inner.kwargs == [{"prompt": build}]


def test_run_split_passes_parts_and_extra_kwargs(factory):
    inner = FakeGuard()
    guard, _ = _wrap(inner, factory)

    def parts(t):
        return [t]

    asyncio.run(guard.run_split("q", _ctx(), parts=parts, extra=1))
    assert inner.kwargs == [{"parts": parts, "extra": 1}]


def test_block_still_applies_with_extra_kwargs(factory):
    inner = FakeGuard()
    guard, _ = _wrap(inner, factory)
    with factory() as db:
        block(db, "sess-1", user_id="u-1", reason="operator", blocked_by="op", now=NOW)
    with pytest.raises(RateLimitedError):
        asyncio.run(guard.run("q", _ctx(), prompt=str))
    assert inner.calls == 0  # 차단된 세션은 인자가 있어도 안쪽을 부르지 않는다


def test_wrapper_exposes_inner_attributes(factory):
    inner = FakeGuard()
    inner.canaries = ("x",)
    guard, _ = _wrap(inner, factory)
    assert guard.canaries == ("x",)


def test_wrapper_wired_in_fastapi_adapter():
    """`get_guardrail()` 이 돌려주는 바깥 래퍼가 C7 이고 그 안이 D16 인지(라우터를 거치지 않을 길이 없다)."""
    from app.features.ratelimit.guard import RateLimitedGuardrail
    from app.guardrail import fastapi as adapter

    outer = adapter._limited()
    assert isinstance(outer, RateLimitedGuardrail)
    assert isinstance(outer.inner, SessionBlockGuardrail)

