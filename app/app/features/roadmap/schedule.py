"""C14 — 주차별 학습 배치 (순수 로직, DB·LLM·API 무관).

학습 역량(C10 갭에 콘텐츠를 붙인 것)을 **주당 가용 시간**에 맞춰 **주차별로 배치**한다.
입력 순서를 그대로 지킨다 — C10이 이미 중요도순(필수→우대)으로 정렬하므로 **필수가 앞 주차**에 온다.

긴 과정 처리(docs/C14.md): 내일배움카드 과정은 수백 시간짜리도 있어 "주당 N시간"을 넘는다.
→ 한 과정을 **여러 주로 쪼갠다**(N주 블록). `hours_this_week`에 그 주 분량을 담는다.

LLM은 여기 없다 — 이 배치 결과 위에 "왜 이 순서인지" 설명만 A8 경유로 붙인다(통합 단계).
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class LearningItem:
    """배치할 학습 항목 1건 = 역량 + 붙은 콘텐츠의 예상 시간.

    `key`·`label`·`importance`는 C10 `LearningGap`에서, `est_hours`·`title`은 콘텐츠(고용24)에서 온다.
    배치는 `est_hours`와 입력 순서만 쓴다(매핑은 호출측 service).
    """

    key: str
    label: str
    importance: str          # required / preferred / mentioned (정렬은 호출측이 끝냄)
    est_hours: float         # 콘텐츠 예상 소요 시간(없으면 0 — 사용자 추가 항목 등)
    title: str = ""          # 표시용 콘텐츠 제목
    slot: int = 0            # 같은 역량의 몇 번째 강좌인가(학습 방법 "전체"면 온라인·오프라인 2칸)


@dataclass(frozen=True)
class ScheduledItem:
    """한 주차에 놓인 항목(+그 주 분량). 긴 과정은 여러 주에 걸쳐 여러 번 등장."""

    item: LearningItem
    week: int
    hours_this_week: float


@dataclass(frozen=True)
class WeeklyPlan:
    week: int
    items: tuple[ScheduledItem, ...]

    @property
    def total_hours(self) -> float:
        return sum(s.hours_this_week for s in self.items)


def build_schedule(
    items: Iterable[LearningItem],
    *,
    weekly_hours: float,
    max_weeks: int | None = None,
) -> list[WeeklyPlan]:
    """항목들을 주당 `weekly_hours`에 맞춰 주차별로 채운다(greedy, 입력 순서 유지).

    - **짧은 과정은 안 쪼갠다** — 남은 용량보다 크면 **통째로 다음 주**로(2h를 1h+1h로 쪼개면 이상).
    - **한 주를 통째로 넘는 과정만** 주 단위로 쪼갠다(예: 12h, 5h/주 → 5+5+2). docs/C14.md "N주 블록".
    - `est_hours <= 0`(사용자 추가·시간미상)은 용량을 안 쓰고 현재 주에 그냥 얹는다.
    - `max_weeks`를 주면 그 주차까지만 배치하고 나머지는 버린다(초과분은 호출측이 "다음 기수" 등 처리).
    """
    if weekly_hours <= 0:
        raise ValueError("weekly_hours must be positive")

    weeks: list[WeeklyPlan] = []
    week_no = 1
    remaining = weekly_hours
    current: list[ScheduledItem] = []

    def close_week() -> bool:
        """현재 주를 확정. max_weeks 초과면 False(중단 신호)."""
        nonlocal week_no, remaining, current
        weeks.append(WeeklyPlan(week=week_no, items=tuple(current)))
        current = []
        week_no += 1
        remaining = weekly_hours
        return max_weeks is None or week_no <= max_weeks

    for item in items:
        if item.est_hours <= 0:
            current.append(ScheduledItem(item=item, week=week_no, hours_this_week=0.0))
            continue

        # 남은 용량에 안 들어가면 현재 주를 닫고 새 주에서 시작(짧은 과정을 쪼개지 않기 위해).
        if item.est_hours > remaining and current:
            if not close_week():
                return weeks

        # 한 주 용량 이하면 통째로, 넘으면 주 단위로 쪼갠다(긴 과정만).
        hours_left = item.est_hours
        while hours_left > 0:
            if remaining <= 0:
                if not close_week():
                    return weeks  # max_weeks 도달 — 나머지 버림
            take = min(hours_left, remaining)
            current.append(ScheduledItem(item=item, week=week_no, hours_this_week=take))
            hours_left -= take
            remaining -= take

    if current:
        weeks.append(WeeklyPlan(week=week_no, items=tuple(current)))
    return weeks
