"""C15 마감 임박 규칙 테스트. DB 불필요(순수)."""
from datetime import date

from app.features.applications.rules import DUE_SOON_DAYS, days_until, is_due_soon

TODAY = date(2026, 10, 22)


def test_days_until():
    assert days_until(date(2026, 10, 29), TODAY) == 7
    assert days_until(date(2026, 10, 22), TODAY) == 0
    assert days_until(date(2026, 10, 20), TODAY) == -2  # 이미 지남
    assert days_until(None, TODAY) is None              # 상시채용


def test_is_due_soon_within():
    assert is_due_soon(date(2026, 10, 29), TODAY) is True   # D-7 경계
    assert is_due_soon(date(2026, 10, 25), TODAY) is True
    assert is_due_soon(date(2026, 10, 22), TODAY) is True   # 오늘 마감


def test_is_due_soon_out_of_range():
    assert is_due_soon(date(2026, 11, 5), TODAY) is False   # 14일 뒤
    assert is_due_soon(date(2026, 10, 20), TODAY) is False  # 이미 지남
    assert is_due_soon(None, TODAY) is False                # 마감 없음


def test_due_soon_days_default():
    assert DUE_SOON_DAYS == 7
