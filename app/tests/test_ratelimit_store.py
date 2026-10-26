"""C7 PostgresStore 통합 테스트 — 실 pgvector(DB) 필요. conftest `db_session` 사용(Docker/CI).

순수 로직은 test_ratelimit.py(InMemoryStore)가 덮고, 여기선 **Postgres 원자적 upsert**의
창 리셋·증가·키 격리를 실 DB로 확인한다. RateLimiter를 PostgresStore에 물려 end-to-end도 본다.
"""
import pytest

from app.features.ratelimit.policy import Limit, RateLimits
from app.features.ratelimit.service import RateLimiter
from app.features.ratelimit.store import PostgresStore
from app.models.ratelimit import RateLimitCounter


@pytest.fixture(autouse=True)
def _ensure_table(db_session):
    # rate_limit_counters 마이그레이션은 B 취합 전이라 alembic head에 없다. PostgresStore SQL을
    # 실 pgvector로 검증하려고 테스트 트랜잭션 안에서 테이블을 만든다(끝나면 롤백으로 사라짐).
    RateLimitCounter.__table__.create(bind=db_session.get_bind(), checkfirst=True)


def test_add_and_get_accumulates(db_session):
    s = PostgresStore(db_session)
    assert s.get("k", window_seconds=60, now=0) == (0, 0.0)
    s.add("k", 1, window_seconds=60, now=0)
    s.add("k", 2, window_seconds=60, now=5)
    count, elapsed = s.get("k", window_seconds=60, now=10)
    assert count == 3 and elapsed == 10


def test_window_resets_after_expiry(db_session):
    s = PostgresStore(db_session)
    s.add("k", 5, window_seconds=60, now=0)
    assert s.get("k", window_seconds=60, now=30)[0] == 5     # 같은 창
    assert s.get("k", window_seconds=60, now=61) == (0, 0.0)  # 창 만료 → 0
    s.add("k", 1, window_seconds=60, now=61)                  # 새 창 시작
    assert s.get("k", window_seconds=60, now=62)[0] == 1


def test_keys_isolated(db_session):
    s = PostgresStore(db_session)
    s.add("a", 3, window_seconds=60, now=0)
    s.add("b", 1, window_seconds=60, now=0)
    assert s.get("a", window_seconds=60, now=1)[0] == 3
    assert s.get("b", window_seconds=60, now=1)[0] == 1


def test_limiter_on_postgres_blocks_after_limit(db_session):
    limits = RateLimits(
        requests_per_min=Limit("req", 3, 60),
        tokens_per_day=Limit("tok", 100, 86_400),
        exfil_per_session=Limit("exfil", 2, 600),
    )
    rl = RateLimiter(PostgresStore(db_session), limits)
    assert rl.check_request("u", now=0).allowed
    assert rl.check_request("u", now=1).allowed
    assert rl.check_request("u", now=2).allowed
    assert not rl.check_request("u", now=3).allowed          # 4번째 거부
    # 탈취 세션
    rl.record_violation("s", now=0)
    rl.record_violation("s", now=1)
    assert not rl.check_session("s", now=2).allowed          # 2회 → 차단
