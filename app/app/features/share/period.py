"""공유 기간 계산 (B10, part2_guide 4.40).

- 사용자는 종료일(날짜)을 고른다. 종료일 하루가 끝나는 순간(다음 날 00:00 KST)에 만료된다
- 기준일(공유일·연장일)을 1일째로 세어 최대 30일째 날까지. 기본은 7일째 날
- 저장은 UTC
"""
from datetime import UTC, date, datetime, time, timedelta, timezone

KST = timezone(timedelta(hours=9), "KST")  # 한국은 일광 절약 시간이 없어 고정 오프셋으로 충분하다
MAX_DAYS = 30
DEFAULT_DAYS = 7


class PeriodInvalid(ValueError):
    pass


def today_kst(now: datetime) -> date:
    return now.astimezone(KST).date()


def default_end(now: datetime) -> date:
    return today_kst(now) + timedelta(days=DEFAULT_DAYS - 1)


def max_end(now: datetime) -> date:
    return today_kst(now) + timedelta(days=MAX_DAYS - 1)


def expires_at_for(end: date) -> datetime:
    return datetime.combine(end + timedelta(days=1), time(0), KST).astimezone(UTC)


def end_date_of(expires_at: datetime) -> date:
    return expires_at.astimezone(KST).date() - timedelta(days=1)


def check_end(end: date, now: datetime) -> None:
    """기준일(오늘, KST)부터 30일째 날까지만 허용."""
    if not today_kst(now) <= end <= max_end(now):
        raise PeriodInvalid()


def iso_z(dt: datetime) -> str:
    """C6 비교용 문자열. 타임존을 Z로 명시(part2_guide 4.39)."""
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
