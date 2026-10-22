"""C15 — 마감 임박 판정 (순수 로직, DB 무관).

`DUE_SOON_DAYS`는 tasks.md "마감 임박 알림"의 기준 일수 — 명세엔 숫자가 없어 기본값(조정 가능).
"""
from __future__ import annotations

from datetime import date

#: 마감 N일 이내면 임박으로 본다(기본 7일). 운영에서 바꾸려면 이 값만 조정.
DUE_SOON_DAYS = 7


def days_until(closes_on: date | None, today: date) -> int | None:
    """마감까지 남은 일수. `closes_on`이 없으면(상시채용 등) None."""
    if closes_on is None:
        return None
    return (closes_on - today).days


def is_due_soon(closes_on: date | None, today: date, *, within: int = DUE_SOON_DAYS) -> bool:
    """마감이 오늘~within일 이내면 True. 이미 지난 마감·마감 없음은 False."""
    remaining = days_until(closes_on, today)
    return remaining is not None and 0 <= remaining <= within
