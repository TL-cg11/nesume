"""C7 — 레이트리밋 카운터 저장소.

키별 **고정 창(fixed window)** 카운터를 둔다: 창이 지나면 리셋, 창 안에선 누적.
인터페이스(`RateLimitStore`) 뒤에 두어 교체 가능하게 한다(docs/C7.md 결정).

- `InMemoryStore` — 개발·단위 테스트용. **프로세스 메모리**라 HPA 다중 파드에선 공유 안 됨 → 운영 금지.
- `PostgresStore` — 운영용. `rate_limit_counters` 테이블에 **원자적 upsert**(INSERT … ON CONFLICT
  DO UPDATE)로 창 리셋/증가. 다중 파드가 같은 행을 보므로 한도가 정확. 세션은 요청별 주입.
  ※ 테이블 모델 등록·마이그레이션은 B 취합 대기. 실행 검증은 Docker(pgvector).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class RateLimitStore(Protocol):
    """창 카운터 저장소. `now`는 호출측이 주입(테스트 고정·운영 time.time)."""

    def get(self, key: str, *, window_seconds: int, now: float) -> tuple[int, float]:
        """현재 창의 (누적 count, 창 시작 후 elapsed초). 창 만료·미존재면 (0, 0.0)."""
        ...

    def add(self, key: str, amount: int, *, window_seconds: int, now: float) -> None:
        """현재 창 카운터를 amount만큼 증가(만료됐으면 새 창으로 리셋 후 amount)."""
        ...


class InMemoryStore:
    """프로세스 메모리 구현(개발·테스트 전용). 다중 파드 공유 불가 — 운영은 PostgresStore."""

    def __init__(self) -> None:
        self._windows: dict[str, tuple[float, int]] = {}  # key -> (window_start, count)

    def get(self, key: str, *, window_seconds: int, now: float) -> tuple[int, float]:
        entry = self._windows.get(key)
        if entry is None:
            return (0, 0.0)
        start, count = entry
        if now - start >= window_seconds:
            return (0, 0.0)  # 창 만료 → 리셋된 것으로 본다
        return (count, now - start)

    def add(self, key: str, amount: int, *, window_seconds: int, now: float) -> None:
        entry = self._windows.get(key)
        if entry is None or now - entry[0] >= window_seconds:
            self._windows[key] = (now, amount)  # 새 창
        else:
            self._windows[key] = (entry[0], entry[1] + amount)


class PostgresStore:
    """운영용. `rate_limit_counters` 행을 요청별 세션으로 읽고/원자적 upsert한다.

    다중 파드가 같은 행을 보므로 한도가 정확. `add`는 창 만료면 리셋, 아니면 증가를 **한 문장**으로
    처리(ON CONFLICT DO UPDATE + CASE) — 두 파드가 동시에 와도 DB가 직렬화한다.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, key: str, *, window_seconds: int, now: float) -> tuple[int, float]:
        from app.models.ratelimit import RateLimitCounter

        row = self.session.get(RateLimitCounter, key)
        if row is None or now - row.window_start >= window_seconds:
            return (0, 0.0)  # 없거나 창 만료 → 리셋된 것으로 본다
        return (row.count, now - row.window_start)

    def add(self, key: str, amount: int, *, window_seconds: int, now: float) -> None:
        from sqlalchemy import case
        from sqlalchemy.dialects.postgresql import insert

        from app.models.ratelimit import RateLimitCounter

        table = RateLimitCounter.__table__
        expired = (now - table.c.window_start) >= window_seconds  # 기존 행의 창이 지났나
        stmt = insert(table).values(key=key, window_start=now, count=amount)
        stmt = stmt.on_conflict_do_update(
            index_elements=["key"],
            set_={
                "window_start": case((expired, now), else_=table.c.window_start),
                "count": case((expired, amount), else_=table.c.count + amount),
            },
        )
        self.session.execute(stmt)
