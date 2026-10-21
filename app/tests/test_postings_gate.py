"""C4 수집 건강성 게이트 테스트. DB 불필요(순수 로직)."""
from app.postings.health import evaluate_health

# 평소 ~1000건이라고 보는 최근 정상 수집 이력(7회 이상)
HISTORY = [1000, 1020, 980, 1010, 990, 1005, 995]


def test_bootstrap_when_history_short():
    # 이력 부족 → 수집은 정상 처리하되 사라짐 처리는 보류
    d = evaluate_health(1000, [1000, 1000])
    assert d.healthy is True
    assert d.process_absences is False
    assert d.reason == "bootstrap"


def test_ok_normal_volume():
    d = evaluate_health(1000, HISTORY)
    assert d.healthy is True
    assert d.process_absences is True


def test_ok_minor_dip_within_rel():
    # 85%는 상대 가드(80%) 위 → 정상
    d = evaluate_health(850, HISTORY)
    assert d.healthy is True
    assert d.process_absences is True


def test_below_relative_guard():
    # 70% → 상대 급감 → 비정상, 사라짐 처리 동결
    d = evaluate_health(700, HISTORY)
    assert d.healthy is False
    assert d.process_absences is False
    assert "below-rel" in d.reason


def test_below_absolute_floor():
    # 30% → 절대 하한(50%) 위반 → 비정상 (서서히 끓기 방지)
    d = evaluate_health(300, HISTORY)
    assert d.healthy is False
    assert d.process_absences is False
    assert "below-floor" in d.reason


def test_full_outage_zero_count():
    d = evaluate_health(0, HISTORY)
    assert d.healthy is False
    assert d.process_absences is False


def test_baseline_is_median_not_mean():
    # 이상치 한 건(10000)이 섞여도 중앙값은 ~1000 → 평소 수집이 비정상으로 안 뜸
    hist = [1000, 1000, 1000, 1000, 1000, 1000, 10000]
    d = evaluate_health(1000, hist)
    assert d.baseline == 1000
    assert d.healthy is True


def test_growth_rebaselines():
    # 꾸준히 늘어난 이력이면 기준선도 높아져, 과거 기준 급증은 정상으로 본다
    hist = [2000, 2050, 1980, 2100, 2000, 2020, 1990]
    d = evaluate_health(2000, hist)
    assert d.healthy is True
    assert d.process_absences is True
