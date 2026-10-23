"""C14 주차 배치 테스트. DB·LLM·API 불필요(순수)."""
import pytest

from app.features.roadmap.schedule import LearningItem, build_schedule


def _item(key, hours, importance="required"):
    return LearningItem(key=key, label=key.upper(), importance=importance, est_hours=hours, title=key)


def test_fills_within_weekly_hours():
    items = [_item("a", 2), _item("b", 2), _item("c", 2)]  # 5h/주 → 1주: a,b(4h), 2주: c
    weeks = build_schedule(items, weekly_hours=5)
    assert len(weeks) == 2
    assert [s.item.key for s in weeks[0].items] == ["a", "b"]
    assert weeks[0].total_hours == 4
    assert [s.item.key for s in weeks[1].items] == ["c"]


def test_order_preserved_so_required_first():
    # 호출측(C10)이 정렬해 넘긴 순서를 그대로 유지 → 필수가 앞 주차
    items = [_item("req", 5, "required"), _item("pref", 5, "preferred")]
    weeks = build_schedule(items, weekly_hours=5)
    assert weeks[0].items[0].item.key == "req"
    assert weeks[1].items[0].item.key == "pref"


def test_long_course_split_across_weeks():
    # 12h 과정, 5h/주 → 5+5+2로 3주에 쪼개짐
    weeks = build_schedule([_item("big", 12)], weekly_hours=5)
    assert len(weeks) == 3
    assert [w.total_hours for w in weeks] == [5, 5, 2]
    assert all(s.item.key == "big" for w in weeks for s in w.items)


def test_zero_hour_item_does_not_consume_capacity():
    # 사용자 추가·시간미상(0h)은 용량 안 쓰고 현재 주에 얹힘
    items = [_item("free", 0), _item("a", 5)]
    weeks = build_schedule(items, weekly_hours=5)
    assert len(weeks) == 1
    keys = [s.item.key for s in weeks[0].items]
    assert "free" in keys and "a" in keys
    assert weeks[0].total_hours == 5  # free는 0h


def test_max_weeks_truncates_overflow():
    items = [_item("a", 5), _item("b", 5), _item("c", 5)]
    weeks = build_schedule(items, weekly_hours=5, max_weeks=2)
    assert len(weeks) == 2
    assert [w.items[0].item.key for w in weeks] == ["a", "b"]  # c는 버려짐


def test_weekly_hours_must_be_positive():
    with pytest.raises(ValueError):
        build_schedule([_item("a", 1)], weekly_hours=0)


def test_empty_items_gives_empty_schedule():
    assert build_schedule([], weekly_hours=5) == []
